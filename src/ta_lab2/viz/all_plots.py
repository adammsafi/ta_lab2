from __future__ import annotations
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt


# --- small utility: choose a time column if present ---
def _pick_time_index(d: pd.DataFrame) -> pd.Index:
    for c in ("timestamp", "timeclose", "date", "timeopen"):
        if c in d.columns:
            return pd.to_datetime(d[c], errors="coerce")
    return d.index


# --- Price + EMAs (+ optional slopes & flips), newest bar on the right ---
def plot_ema_with_trend(
    df: pd.DataFrame,
    price_col: str = "close",
    ema_cols=None,
    trend_col: str = "trend_state",
    *,
    include_slopes: bool = True,
    include_flips: bool = True,
    n: int = 1000,
):
    d = df.tail(n).copy()
    # If caller didn’t pass explicit EMA cols, auto-detect like <base>_ema_<p>
    if ema_cols is None:
        ema_cols = [
            c
            for c in d.columns
            if c.lower().startswith(
                ("open_ema_", "high_ema_", "low_ema_", "close_ema_")
            )
        ]
        if not ema_cols:  # fall back to any column starting with "ema_"
            ema_cols = [c for c in d.columns if c.lower().startswith("ema_")]

    x = np.arange(len(d))  # newest-on-top visual: invert x later
    t = _pick_time_index(d)

    fig, ax = plt.subplots(figsize=(12, 6))
    ax.plot(x, d[price_col].to_numpy(), lw=1.3, label=price_col)

    # left axis: EMAs
    for c in ema_cols:
        if c in d:
            ax.plot(x, d[c].to_numpy(), lw=1.0, label=c)

    ax2 = None
    if include_slopes:
        # try to find slope columns that match attached helpers: *_d1_bps / *_d1_norm
        slope_cols = [
            c for c in d.columns if c.endswith("_d1_bps") or c.endswith("_d1_norm")
        ]
        if slope_cols:
            ax2 = ax.twinx()
            for sc in slope_cols:
                ax2.plot(x, d[sc].to_numpy(), lw=0.8, alpha=0.8, label=sc)
            ax2.axhline(0, ls="--", lw=1, alpha=0.8)

            # match attached “sensible y-lims from all drawn slope series”
            right_vals = np.concatenate(
                [
                    d[c].to_numpy()[~np.isnan(d[c].to_numpy())]
                    for c in slope_cols
                    if c in d
                ]
            )
            if right_vals.size:
                qlo, qhi = np.percentile(right_vals, [1, 99])
                span = qhi - qlo
                pad = (span * 0.25) if np.isfinite(span) and span > 0 else 10
                ax2.set_ylim(qlo - pad, qhi + pad)

    # optional flip markers (columns named like <base>_ema_<p>_flip), as in your attached utils
    if include_flips:
        flip_cols = [
            c for c in d.columns if c.endswith("_ema_21_flip") or c.endswith("_flip")
        ]
        # de-dup to avoid plotting tons of labels
        plotted = False
        for fc in flip_cols:
            if fc in d:
                idx = np.where(d[fc].to_numpy())[0]
                if idx.size:
                    # mark flips on the shortest EMA series available for better alignment
                    base_for_mark = ema_cols[0] if ema_cols else price_col
                    ax.scatter(
                        idx,
                        d[base_for_mark].to_numpy()[idx],
                        c="k",
                        marker="x",
                        s=40,
                        label=("flip" if not plotted else None),
                    )
                    plotted = True

    # optional trend track (your custom column)
    if trend_col in d.columns:
        ax3 = ax.twinx()
        ax3.spines.right.set_position(("axes", 1.08))
        ax3.plot(x, d[trend_col].to_numpy(), lw=0.8, alpha=0.25)
        ax3.set_yticks([-1, 0, 1])
        ax3.set_ylabel("trend")

    # newest bar on the RIGHT to match your figures
    ax.invert_xaxis()
    ax.set_xticks(np.linspace(0, len(d) - 1, 6, dtype=int))
    ax.set_xticklabels(
        pd.to_datetime(t)
        .astype("datetime64[ns]")
        .to_series()
        .iloc[ax.get_xticks().astype(int)]
        .dt.date.astype(str),
        rotation=0,
    )

    ax.set_title("Price + EMAs + Slopes/Flips (newest on right)")
    ax.set_xlabel("bars")
    ax.legend(loc="upper left")
    if include_slopes and ax2:
        ax2.legend(loc="upper right")
    plt.tight_layout()
    return ax


# --- Consolidated EMAs view (mirrors daf.plot_consolidated_emas) ---
def plot_consolidated_emas_like(
    df: pd.DataFrame,
    base_col: str = "close",
    periods=(21, 50, 100, 200),
    *,
    include_slopes: bool = True,
    include_flips: bool = True,
    n: int = 1000,
):
    d = df.tail(n).copy()
    x = np.arange(len(d))
    t = _pick_time_index(d)

    fig, ax = plt.subplots(figsize=(12, 6))

    # all EMAs for this base on left axis
    for p in periods:
        ema = f"{base_col}_ema_{p}"
        if ema not in d:
            continue
        ax.plot(x, d[ema].to_numpy(), lw=1.2, label=ema)

    ax.invert_xaxis()
    ax.set_title(f"{base_col.upper()} EMAs {', '.join(map(str, periods))}")
    ax.set_xlabel("bars (newest on right)")
    ax.legend(loc="upper left")

    if include_slopes:
        ax2 = ax.twinx()
        right_series = []
        for p in periods:
            bps = f"{base_col}_ema_{p}_d1_bps"
            pct = f"{base_col}_ema_{p}_d1_norm"
            if bps in d:
                ax2.plot(
                    x, d[bps].to_numpy(), alpha=0.5, lw=0.9, label=f"slope bps (p={p})"
                )
                right_series.append(d[bps].to_numpy())
            if pct in d:
                ax2.plot(
                    x, d[pct].to_numpy(), alpha=0.5, lw=0.9, label=f"slope % (p={p})"
                )
                right_series.append(d[pct].to_numpy())

            if include_flips:
                flip = f"{base_col}_ema_{p}_flip"
                if flip in d:
                    idx = np.where(d[flip].to_numpy())[0]
                    if idx.size:
                        ax.scatter(
                            idx,
                            d[f"{base_col}_ema_{p}"].to_numpy()[idx],
                            c="k",
                            marker="x",
                            s=40,
                            label=f"flip {p}",
                        )
        ax2.axhline(0, ls="--", lw=1, alpha=0.8)
        ax2.legend(loc="upper right")

        if right_series:
            rs = np.concatenate([r[~np.isnan(r)] for r in right_series if r.size])
            if rs.size:
                qlo, qhi = np.percentile(rs, [1, 99])
                span = qhi - qlo
                pad = (span * 0.25) if np.isfinite(span) and span > 0 else 10
                ax2.set_ylim(qlo - pad, qhi + pad)

    plt.tight_layout()
    return ax


# --- Realized volatility panel: Parkinson, GK, RS (+ optional stdev of log returns) ---
def plot_realized_vol(
    df: pd.DataFrame,
    *,
    windows=(30, 60, 90),
    include_logret_stdev: bool = True,
    n: int = 1000,
):
    d = df.tail(n).copy()
    x = np.arange(len(d))
    t = _pick_time_index(d)

    fig, ax = plt.subplots(figsize=(12, 4))
    plotted = False

    # match generated names: parkinson_vol_<w>, gk_vol_<w> (or gk_vol_<w>), rs_vol_<w>
    for w in windows:
        for name in (f"parkinson_vol_{w}", f"gk_vol_{w}", f"rs_vol_{w}"):
            if name in d.columns:
                ax.plot(x, d[name].to_numpy(), lw=1.0, label=name)
                plotted = True

    # optional: rolling stdev of log returns (add_logret_stdev_vol)
    if include_logret_stdev:
        stdev_cols = [
            c
            for c in d.columns
            if c.endswith(tuple(f"_vol_stdev_{w}" for w in windows))
        ]
        for c in stdev_cols:
            ax.plot(x, d[c].to_numpy(), lw=0.9, alpha=0.8, label=c)

    if not plotted and not [c for c in d.columns if c.endswith("_vol_stdev_")]:
        print("[plot skipped] No realized-vol columns found.")
        return ax

    ax.invert_xaxis()
    ax.set_title("Realized Volatility (rolling)")
    ax.set_xlabel("bars (newest on right)")
    ax.legend(loc="upper left", ncol=2)
    plt.tight_layout()
    return ax
