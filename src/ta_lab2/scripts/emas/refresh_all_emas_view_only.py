from __future__ import annotations

from ta_lab2.scripts.refresh_cmc_emas import refresh


def main() -> None:
    # ids list is irrelevant here, but refresh() requires one; use an empty list
    # and only refresh the view.
    refresh(
        ids=[],
        start=None,
        end=None,
        db_url=None,
        update_daily=False,
        update_multi_tf=False,
        update_cal_multi_tf=False,
        refresh_all_emas_view=True,
        refresh_price_emas_view=False,
        refresh_price_emas_d1d2_view=False,
    )


if __name__ == "__main__":
    main()
