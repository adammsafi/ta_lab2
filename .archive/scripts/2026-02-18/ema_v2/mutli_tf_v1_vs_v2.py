# -*- coding: utf-8 -*-
"""
Created on Sun Dec  7 07:13:22 2025

@author: asafi
"""

import pandas as pd
from sqlalchemy import create_engine, text
import matplotlib.pyplot as plt

# --------------------------------------------------------
# Config
# --------------------------------------------------------

db_url = "postgresql+psycopg2://postgres:3400@localhost:5432/marketdata"  # or reuse the loaded env var

asset_id = 1

# ---------------------------------------
# Choose tf/periods that exist in BOTH v1 and v2
# ---------------------------------------

tf_periods = [
    ("10D", 21),
    ("1M", 21),
    ("6M", 21),
]

date_windows = [
    ("Early history", "2010-01-01", "2015-12-31"),
    ("Mid 2010s", "2016-01-01", "2018-06-30"),
    ("Recent", "2020-01-01", None),  # None = through last date
]

# --------------------------------------------------------
# Load data
# --------------------------------------------------------

engine = create_engine(db_url)

with engine.begin() as conn:
    # Price history for id=1
    df_price = pd.read_sql(
        text(
            """
            SELECT id,
            timestamp as ts,
            close
            FROM cmc_price_histories7
            WHERE id = :id
            ORDER BY ts
        """
        ),
        conn,
        params={"id": asset_id},
    )

    # Original multi_tf
    df_mt1 = pd.read_sql(
        text(
            """
            SELECT id, ts, tf, period, ema
            FROM cmc_ema_multi_tf
            WHERE id = :id
        """
        ),
        conn,
        params={"id": asset_id},
    )

    # New multi_tf_v2
    df_mt2 = pd.read_sql(
        text(
            """
            SELECT id, ts, tf, period, ema
            FROM cmc_ema_multi_tf_v2
            WHERE id = :id
        """
        ),
        conn,
        params={"id": asset_id},
    )

# Ensure timestamps are UTC datetime and sort
for df in (df_price, df_mt1, df_mt2):
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    df.sort_values("ts", inplace=True)

# Set index for easy slicing
df_price.set_index("ts", inplace=True)
df_mt1.set_index("ts", inplace=True)
df_mt2.set_index("ts", inplace=True)

# --------------------------------------------------------
# Helper: get EMA series for a given tf/period
# --------------------------------------------------------


def get_ema_series(df_mt: pd.DataFrame, tf: str, period: int) -> pd.Series:
    """Return EMA series indexed by ts for given tf/period."""
    sub = df_mt[(df_mt["tf"] == tf) & (df_mt["period"] == period)].copy()
    if sub.empty:
        return pd.Series(dtype=float)

    # Make sure ts is the index
    if "ts" in sub.columns:
        sub = sub.set_index("ts")

    sub.sort_index(inplace=True)
    return sub["ema"]


# ---------------------------------------
# Plotting
# ---------------------------------------

for title, start_str, end_str in date_windows:
    if end_str is not None:
        mask_price = (df_price.index >= start_str) & (df_price.index <= end_str)
    else:
        mask_price = df_price.index >= start_str

    price_slice = df_price.loc[mask_price]

    if price_slice.empty:
        print(f"[WARN] No price data for window {title}; skipping.")
        continue

    fig, ax = plt.subplots(figsize=(12, 6))

    # Price
    ax.plot(
        price_slice.index, price_slice["close"], label="Price (close)", linewidth=1.0
    )

    start = price_slice.index[0]
    end = price_slice.index[-1]

    for tf, period in tf_periods:
        ema1 = get_ema_series(df_mt1, tf, period)  # orig
        ema2 = get_ema_series(df_mt2, tf, period)  # v2

        ema1_slice = ema1.loc[start:end] if not ema1.empty else ema1
        ema2_slice = ema2.loc[start:end] if not ema2.empty else ema2

        # Solid line = original table
        if not ema1_slice.empty:
            ax.plot(
                ema1_slice.index,
                ema1_slice.values,
                linestyle="-",
                linewidth=1.0,
                label=f"orig {tf} p={period}",
            )

        # Dashed line = v2 table
        if not ema2_slice.empty:
            ax.plot(
                ema2_slice.index,
                ema2_slice.values,
                linestyle="-",
                linewidth=1.0,
                label=f"v2 {tf} p={period}",
            )

    ax.set_title(f"id={asset_id} — {title}")
    ax.set_xlabel("Date")
    ax.set_ylabel("Price / EMA")
    ax.legend()
    ax.grid(True)

    plt.tight_layout()
    plt.show()
