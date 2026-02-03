# -*- coding: utf-8 -*-
"""
Created on Mon Nov 24 21:59:27 2025

@author: asafi
"""
from __future__ import annotations

import subprocess
from typing import List, Optional

from sqlalchemy import create_engine, text

from ta_lab2.config import TARGET_DB_URL


def get_all_asset_ids(db_url: Optional[str] = None) -> List[str]:
    """
    Load all distinct asset ids from cmc_price_histories7 as strings.
    """
    engine = create_engine(db_url or TARGET_DB_URL)
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT DISTINCT id FROM cmc_price_histories7 ORDER BY id;")
        ).fetchall()
    return [str(r[0]) for r in rows]


def main(db_url: Optional[str] = None) -> None:
    """
    Refresh cmc_ema_daily and cmc_ema_multi_tf for ALL assets in cmc_price_histories7,
    and refresh the EMA views, by invoking the existing refresh_cmc_emas script.
    """
    ids = get_all_asset_ids(db_url=db_url)
    if not ids:
        raise RuntimeError("No ids found in cmc_price_histories7.")

    # Build the CLI arguments for refresh_cmc_emas.py
    cli_args = [
        "python",
        "-m",
        "ta_lab2.scripts.refresh_cmc_emas",
        "--ids",
        *ids,
        "--update-daily",
        "--update-multi-tf",
        "--refresh-all-emas-view",
        "--refresh-price-emas-view",
        "--refresh-price-emas-d1d2-view",
    ]

    # If you ever want to override DB URL on the CLI, you can append:
    # if db_url is not None:
    #     cli_args.extend(["--db-url", db_url])

    print("Running:", " ".join(cli_args))
    subprocess.run(cli_args, check=True)


if __name__ == "__main__":
    main()
