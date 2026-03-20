from __future__ import annotations

"""
DEPRECATED: sync_price_bars_multi_tf_u.py

All 5 price bar builders now write directly to price_bars_multi_tf_u
with alignment_source column set at write time. This sync intermediary
is no longer needed and will be removed in Phase 78.

Previously synced price bars from 5 source tables into:
  public.price_bars_multi_tf_u

alignment_source derived from table name:
  price_bars_multi_tf          -> multi_tf
  price_bars_multi_tf_cal_us   -> multi_tf_cal_us
  price_bars_multi_tf_cal_iso  -> multi_tf_cal_iso
  price_bars_multi_tf_cal_anchor_us  -> multi_tf_cal_anchor_us
  price_bars_multi_tf_cal_anchor_iso -> multi_tf_cal_anchor_iso

To verify data, query price_bars_multi_tf_u with alignment_source filter.
"""


U_TABLE = "public.price_bars_multi_tf_u"
PK_COLS = ["id", "tf", "bar_seq", "venue_id", "timestamp", "alignment_source"]
SOURCE_PREFIX = "price_bars_"

SOURCES = [
    "public.price_bars_multi_tf",
    "public.price_bars_multi_tf_cal_us",
    "public.price_bars_multi_tf_cal_iso",
    "public.price_bars_multi_tf_cal_anchor_us",
    "public.price_bars_multi_tf_cal_anchor_iso",
]


def main() -> None:
    """DEPRECATED: All 5 price bar builders now write directly to price_bars_multi_tf_u.

    This sync script is no longer needed. It will be removed in Phase 78.
    To verify data, query price_bars_multi_tf_u with alignment_source filter.
    """
    print(
        "DEPRECATED: sync_price_bars_multi_tf_u.py is no longer needed.\n"
        "All 5 price bar builders now write directly to price_bars_multi_tf_u\n"
        "with alignment_source column. This script will be removed in Phase 78.\n"
        "Exiting with code 0 (no-op)."
    )


if __name__ == "__main__":
    main()
