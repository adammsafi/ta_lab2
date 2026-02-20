import os
from datetime import datetime
import numpy as np
import pandas as pd
from sqlalchemy import create_engine, text
import matplotlib.pyplot as plt

# -----------------------------
# CONFIG
# -----------------------------
db_url = "postgresql+psycopg2://postgres:3400@localhost:5432/marketdata"
asset_id = 1

TF = "180D"
PERIOD = 10

date_windows = [
    ("Early history", "2010-01-01", "2015-12-31"),
    ("Mid 2010s", "2016-01-01", "2018-06-30"),
    ("Recent", "2020-01-01", None),
]

engine = create_engine(db_url)


def dbg_df(name, df):
    if df is None or df.empty:
        print(f"[DBG] {name}: EMPTY")
        return
    print(
        f"[DBG] {name}: rows={len(df):,} ts_min={df['ts'].min()} ts_max={df['ts'].max()}"
    )
    if "tf" in df.columns:
        print(
            f"[DBG] {name}: unique tf={sorted(df['tf'].unique().tolist())[:10]} ... (n={df['tf'].nunique()})"
        )


def parse_tf_days(tf: str) -> int:
    tf = tf.strip().upper()
    if tf.endswith("D"):
        return int(tf[:-1])
    raise ValueError(f"Unsupported TF for this script: {tf} (expected like '180D')")


# -----------------------------
# LOAD DATA
# -----------------------------
with engine.begin() as conn:
    df_price = pd.read_sql(
        text(
            """
            SELECT id, "timestamp" AS ts, close
            FROM public.cmc_price_histories7
            WHERE id = :id
            ORDER BY ts
        """
        ),
        conn,
        params={"id": asset_id},
    )

    df_v1 = pd.read_sql(
        text(
            """
            SELECT id, ts, tf, period, ema, roll
            FROM public.cmc_ema_multi_tf
            WHERE id=:id AND tf=:tf AND period=:p
            ORDER BY ts
        """
        ),
        conn,
        params={"id": asset_id, "tf": TF, "p": PERIOD},
    )

    df_v2 = pd.read_sql(
        text(
            """
            SELECT id, ts, tf, period, ema, roll
            FROM public.cmc_ema_multi_tf_v2
            WHERE id=:id AND tf=:tf AND period=:p
            ORDER BY ts
        """
        ),
        conn,
        params={"id": asset_id, "tf": TF, "p": PERIOD},
    )

# -----------------------------
# NORMALIZE TIMESTAMPS
# -----------------------------
for df in (df_price, df_v1, df_v2):
    df["ts"] = pd.to_datetime(df["ts"], utc=True, errors="coerce")
    df.dropna(subset=["ts"], inplace=True)
    df.sort_values("ts", inplace=True)

print(
    f"[DBG] price rows={len(df_price):,} ts_min={df_price.ts.min()} ts_max={df_price.ts.max()}"
)
print(f"[DBG] v1 rows={len(df_v1):,}")
print(f"[DBG] v2 rows={len(df_v2):,}")

if df_v1.empty or df_v2.empty:
    print(
        "[STOP] v1 or v2 is empty for TF/PERIOD. Likely tf label mismatch (e.g. you have 6M not 180D), or not populated."
    )
    with engine.begin() as conn:
        df_tfs_v1 = pd.read_sql(
            text(
                """SELECT tf, COUNT(*) n FROM public.cmc_ema_multi_tf WHERE id=:id GROUP BY 1 ORDER BY n DESC LIMIT 50"""
            ),
            conn,
            params={"id": asset_id},
        )
        df_tfs_v2 = pd.read_sql(
            text(
                """SELECT tf, COUNT(*) n FROM public.cmc_ema_multi_tf_v2 WHERE id=:id GROUP BY 1 ORDER BY n DESC LIMIT 50"""
            ),
            conn,
            params={"id": asset_id},
        )
    print("[INFO] v1 tf counts (top 50):")
    print(df_tfs_v1.to_string(index=False))
    print("[INFO] v2 tf counts (top 50):")
    print(df_tfs_v2.to_string(index=False))
    raise SystemExit()

# -----------------------------
# BUILD INDEXED SERIES
# -----------------------------
p = (
    df_price[["ts", "close"]]
    .drop_duplicates("ts", keep="last")
    .set_index("ts")
    .sort_index()
)
v1 = (
    df_v1[["ts", "ema", "roll"]]
    .drop_duplicates("ts", keep="last")
    .set_index("ts")
    .sort_index()
)
v2 = (
    df_v2[["ts", "ema", "roll"]]
    .drop_duplicates("ts", keep="last")
    .set_index("ts")
    .sort_index()
)

# Exact-TS join coverage
exact_join = p.join(
    v1.rename(columns={"ema": "ema_v1", "roll": "roll_v1"}), how="left"
).join(v2.rename(columns={"ema": "ema_v2", "roll": "roll_v2"}), how="left")
print(
    "[DBG] exact-ts match counts:",
    exact_join[["ema_v1", "ema_v2"]].notna().sum().to_dict(),
    "out_rows=",
    len(exact_join),
)

# Day join fallback
p_day = p.copy()
p_day["ts_day"] = p_day.index.floor("D")
p_day = p_day.drop_duplicates("ts_day", keep="last").set_index("ts_day").sort_index()

v1_day = v1.copy()
v1_day["ts_day"] = v1_day.index.floor("D")
v1_day = v1_day.drop_duplicates("ts_day", keep="last").set_index("ts_day").sort_index()

v2_day = v2.copy()
v2_day["ts_day"] = v2_day.index.floor("D")
v2_day = v2_day.drop_duplicates("ts_day", keep="last").set_index("ts_day").sort_index()

day_join = p_day.join(
    v1_day.rename(columns={"ema": "ema_v1", "roll": "roll_v1"}), how="left"
).join(v2_day.rename(columns={"ema": "ema_v2", "roll": "roll_v2"}), how="left")
print(
    "[DBG] day-join match counts:",
    day_join[["ema_v1", "ema_v2"]].notna().sum().to_dict(),
    "out_rows=",
    len(day_join),
)

use_day = (day_join["ema_v1"].notna().sum() + day_join["ema_v2"].notna().sum()) > (
    exact_join["ema_v1"].notna().sum() + exact_join["ema_v2"].notna().sum()
)

base = day_join if use_day else exact_join
base.index.name = "ts_day" if use_day else "ts"
print(f"[DBG] using {'DAY' if use_day else 'EXACT TS'} join for output.")


# -----------------------------
# CRITICAL FIX:
# Build canonical schedule from PRICE (bar-space), NOT from v1 rows.
#
# Rationale: your v1/v2 tables often only START storing rows once seeded (e.g. day 1800).
# If you derive canonical timestamps from v1, your "10th canonical" becomes 10 canonicals AFTER day 1800,
# which is exactly how you end up at ~day 3420.
#
# Here we define canonical closes for TF="180D" as every 180th DAILY bar in the price history:
# i.e. day 180, 360, ..., 1800, 1980, ...
# -----------------------------
TF_DAYS = parse_tf_days(TF)


def canonical_index_barspace(
    price_index: pd.DatetimeIndex, tf_days: int
) -> pd.DatetimeIndex:
    # price_index is assumed daily (or at least one row per day after your day-join choice).
    # canonical close is every tf_days-th bar, counting from the start (1-based).
    n = len(price_index)
    if n == 0:
        return pd.DatetimeIndex([])
    pos = np.arange(n)  # 0-based
    mask = ((pos + 1) % tf_days) == 0
    return pd.DatetimeIndex(price_index[mask])


# Choose the price index we are operating in (same as base output)
# For DAY join, base index is already daily buckets.
# For EXACT join, price index is daily close timestamps from cmc_price_histories7.
price_series = base["close"].astype("float64")
canonical_index = canonical_index_barspace(
    pd.DatetimeIndex(price_series.index), TF_DAYS
)

canon_set = set(canonical_index.tolist())
seed_ts_expected = (
    canonical_index[PERIOD - 1] if len(canonical_index) >= PERIOD else None
)

print(
    f"[DBG] canonical (bar-space) tf_days={TF_DAYS}: n={len(canonical_index):,} "
    f"first={canonical_index.min() if len(canonical_index) else None} "
    f"seed_expected={seed_ts_expected}"
)


# -----------------------------
# V3 (DOC) — SMA-SEED ON NTH CANONICAL CLOSE, THEN EMA ON CANONICALS + PREVIEW DAILY
# -----------------------------
def compute_v3_doc(
    price: pd.Series, canonical_idx: pd.DatetimeIndex, period: int
) -> pd.Series:
    """
    v3(doc) with explicit "needs N canonical closes" seeding:

      Canonical EMA:
        - First emitted value occurs at the Nth canonical close.
        - Value at Nth canonical close = SMA(first N canonical closes).
        - After that: standard EMA recursion on canonical closes only.

      Preview (non-canonical):
        - Only after seeded.
        - Recursively updates daily from last canonical EMA state.

      Output:
        - NaN until seeded (strictly nothing before seed canonical close).
    """
    alpha = 2.0 / (period + 1.0)
    ema = pd.Series(index=price.index, dtype="float64")

    is_can = price.index.isin(canonical_idx)
    can_prices = price.loc[is_can].copy()

    if can_prices.empty:
        return ema

    can_ts = can_prices.index
    if len(can_ts) < period:
        return ema

    seed_ts = can_ts[period - 1]
    seed_val = float(can_prices.iloc[:period].mean())

    can_ema = pd.Series(index=can_ts, dtype="float64")
    can_ema.loc[seed_ts] = seed_val

    prev = seed_val
    seeded = False

    for t in can_ts:
        if t == seed_ts:
            seeded = True
            prev = seed_val
            continue
        if not seeded:
            continue
        px = float(can_prices.loc[t])
        prev = alpha * px + (1.0 - alpha) * prev
        can_ema.loc[t] = prev

    prev_full = np.nan
    for t in price.index:
        px = float(price.loc[t])

        if t in can_ema.index and not np.isnan(can_ema.loc[t]):
            prev_full = float(can_ema.loc[t])
            ema.loc[t] = prev_full
            continue

        if np.isnan(prev_full):
            ema.loc[t] = np.nan
            continue

        prev_full = alpha * px + (1.0 - alpha) * prev_full
        ema.loc[t] = prev_full

    # Strict gate: nothing before seed
    ema.loc[ema.index < seed_ts] = np.nan
    return ema


ema_v3 = compute_v3_doc(price_series, canonical_index, PERIOD)

out = base.copy()
out["id"] = asset_id
out["ema_v3_doc"] = ema_v3
out["tf"] = TF
out["period"] = PERIOD
out["is_canonical_used_for_v3"] = out.index.map(lambda x: x in canon_set)

print(
    "[DBG] non-null:", out[["ema_v1", "ema_v2", "ema_v3_doc"]].notna().sum().to_dict()
)
print(
    "[DBG] first non-null:",
    {
        "v1": out["ema_v1"].first_valid_index(),
        "v2": out["ema_v2"].first_valid_index(),
        "v3": out["ema_v3_doc"].first_valid_index(),
    },
)


# -----------------------------
# WRITE CSV
# -----------------------------
os.makedirs("artifacts", exist_ok=True)
ts = datetime.now().strftime("%Y%m%d_%H%M%S")
csv_out = os.path.join("artifacts", f"ema_compare_id{asset_id}_{TF}_p{PERIOD}_{ts}.csv")
out.reset_index().to_csv(csv_out, index=False)
print(f"[OK] wrote CSV: {csv_out}")


# -----------------------------
# PLOTTING
# -----------------------------
def plot_window(title: str, start_str: str, end_str: str | None) -> None:
    idx = out.index
    start = pd.to_datetime(start_str, utc=True)
    end = pd.to_datetime(end_str, utc=True) if end_str else None

    if isinstance(idx, pd.DatetimeIndex):
        m = (idx >= start) if end is None else ((idx >= start) & (idx <= end))
    else:
        idx2 = pd.to_datetime(idx)
        start2 = start.tz_convert(None)
        end2 = end.tz_convert(None) if end is not None else None
        m = (idx2 >= start2) if end2 is None else ((idx2 >= start2) & (idx2 <= end2))

    w = out.loc[m].copy()
    if w.empty:
        print(f"[WARN] empty window: {title}")
        return

    fig, ax = plt.subplots(figsize=(12, 6))
    ax.plot(w.index, w["close"], label="Price (close)", linewidth=1.0)
    ax.plot(w.index, w["ema_v1"], label="v1 (DB)", linewidth=1.0, linestyle="-")
    ax.plot(w.index, w["ema_v2"], label="v2 (DB)", linewidth=1.0, linestyle="--")
    ax.plot(w.index, w["ema_v3_doc"], label="v3(doc)", linewidth=1.0, linestyle=":")

    ax.set_title(f"id={asset_id} — {title} — tf={TF} period={PERIOD}")
    ax.set_xlabel("Date")
    ax.set_ylabel("Price / EMA")
    ax.legend()
    ax.grid(True)
    plt.tight_layout()
    plt.show()


for title, start_str, end_str in date_windows:
    plot_window(title, start_str, end_str)
