# -*- coding: utf-8 -*-
"""
Created on Tue Nov 18 18:43:48 2025

@author: asafi
"""

# run_ema_refresh_examples.py
#
# Convenience script to call refresh() from Spyder / IPython.
# Make sure your working directory in Spyder is the repo root:
#   C:\Users\asafi\Downloads\ta_lab2

from sqlalchemy import create_engine, text

from ta_lab2.config import TARGET_DB_URL
from ta_lab2.scripts.refresh_cmc_emas import refresh


def _get_engine(db_url: str | None = None):
    url = db_url or TARGET_DB_URL
    if not url:
        raise RuntimeError(
            "No DB URL provided and TARGET_DB_URL is not set in config."
        )
    return create_engine(url)


def get_all_ids(db_url: str | None = None) -> list[int]:
    """
    Pull ALL distinct ids from cmc_price_histories7.
    Used for 'refresh everything for all ids' examples.
    """
    engine = _get_engine(db_url)
    with engine.begin() as conn:
        rows = conn.execute(
            text(
                """
                SELECT DISTINCT id
                FROM public.cmc_price_histories7
                ORDER BY id
                """
            )
        ).fetchall()
    ids = [int(r[0]) for r in rows]
    print(f"[run_examples] Using ALL ids from cmc_price_histories7: {ids}")
    return ids


def example_incremental_all_for_btc():
    """
    Default incremental mode (start=None) for BTC only:
    - Insert-only (does NOT update existing EMA rows)
    - Updates both cmc_ema_daily and cmc_ema_multi_tf
    - Refreshes all 3 views
    """
    refresh(
        ids=[1],                 # BTC
        start=None,              # no start -> insert-only mode
        end=None,
        update_daily=True,
        update_multi_tf=True,
        refresh_all_emas_view=True,
        refresh_price_emas_view=True,
        refresh_price_emas_d1d2_view=True,
    )


def example_incremental_subset_multi_ids():
    """
    Incremental insert-only for multiple specific ids.
    No view refresh.
    """
    refresh(
        ids=[1, 1027, 1839],     # BTC, ETH, BNB for example
        start=None,              # insert-only mode
        end=None,
        update_daily=True,
        update_multi_tf=True,
        refresh_all_emas_view=False,
        refresh_price_emas_view=False,
        refresh_price_emas_d1d2_view=False,
    )


def example_recompute_from_date_with_updates():
    """
    Recompute from a specific date and UPDATE existing EMA rows
    in that window (ON CONFLICT DO UPDATE).
    """
    refresh(
        ids=[1, 1027],
        start="2025-10-26",      # recompute + update from here forward
        end=None,
        update_daily=True,
        update_multi_tf=True,
        refresh_all_emas_view=True,
        refresh_price_emas_view=True,
        refresh_price_emas_d1d2_view=True,
    )


def example_only_refresh_views():
    """
    Only refresh the 3 views; no EMA recompute.
    ids is still required by the function, but isn't used when
    update_daily/update_multi_tf are False.
    """
    refresh(
        ids=[1],                 # any id list; not used in this mode
        start=None,
        end=None,
        update_daily=False,
        update_multi_tf=False,
        refresh_all_emas_view=True,
        refresh_price_emas_view=True,
        refresh_price_emas_d1d2_view=True,
    )


def example_incremental_all_ids_all_targets():
    """
    INSERT-ONLY for ALL ids into ALL 5 targets:

    - cmc_ema_daily
    - cmc_ema_multi_tf
    - all_emas
    - cmc_price_with_emas
    - cmc_price_with_emas_d1d2

    Behavior:
        - start=None -> insert-only mode (update_existing = False)
        - existing EMA rows are NOT updated; only new timestamps are inserted.
    """
    ids = get_all_ids()
    refresh(
        ids=ids,
        start=None,              # insert-only; do NOT update existing EMA rows
        end=None,
        update_daily=True,
        update_multi_tf=True,
        refresh_all_emas_view=True,
        refresh_price_emas_view=True,
        refresh_price_emas_d1d2_view=True,
    )


if __name__ == "__main__":
    # Choose which example to run by uncommenting one:

    # example_incremental_all_for_btc()
    # example_incremental_subset_multi_ids()
    # example_recompute_from_date_with_updates()
    # example_only_refresh_views()
    example_incremental_all_ids_all_targets()
