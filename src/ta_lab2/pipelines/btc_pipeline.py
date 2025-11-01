from __future__ import annotations
import pandas as pd

from ta_lab2.features.calendar import expand_datetime_features_inplace
from ta_lab2.features.ema import add_ema_columns, add_ema_d1, add_ema_d2, prepare_ema_helpers
from ta_lab2.features.returns import b2t_pct_delta, b2t_log_delta
from ta_lab2.features.vol import (
    add_volatility_features,            # shim (see vol.py update)
    add_rolling_vol_from_returns_batch, # shim (see vol.py update)
)
from ta_lab2.features.indicators import rsi, macd, bollinger  # lightweight stubs
from ta_lab2.regimes.comovement import (
    compute_ema_comovement_stats,
    compute_ema_comovement_hierarchy,
)
from ta_lab2.regimes.segments import build_flip_segments  # thin wrapper


def _infer_timestamp_col(df: pd.DataFrame, fallback: str = "timestamp") -> str:
    if fallback in df.columns:
        return fallback
    for c in df.columns:
        if "time" in str(c).lower():
            return c
    return fallback


def run_btc_pipeline(
    csv_path: str,
    price_cols=("open", "high", "low", "close"),
    timestamp_col="timestamp",
    ema_windows=(21, 50, 100, 200),
    resample: str | None = None,   # e.g., "1H", "1D"
    returns_modes=("log", "pct"),
    returns_windows=(30, 60, 90),
) -> dict:
    """
    End-to-end, testable pipeline aligned to the modular ta_lab2 layout.
    Returns a dict of key tables for downstream use.
    """
    df = pd.read_csv(csv_path)
    df.columns = [str(c).strip().lower() for c in df.columns]
    timestamp_col = _infer_timestamp_col(df, timestamp_col)
    df = df.rename(columns={timestamp_col: "timestamp"})

    # NOTE: new API name is base_timestamp_col (not ts_col)
    expand_datetime_features_inplace(df, base_timestamp_col="timestamp")

    # Optional resample (OHLCV)
    if resample:
        agg = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
        have = {k: v for k, v in agg.items() if k in df.columns}
        if have:
            df = (
                df.set_index("timestamp")
                  .resample(resample)
                  .agg(have)
                  .dropna()
                  .reset_index()
            )
            expand_datetime_features_inplace(df, base_timestamp_col="timestamp")

    # Indicators (simple stubs to keep imports working)
    if "close" in df.columns:
        out = rsi(df, period=14, price_col="close")
        df[out.name] = out
        df = df.join(macd(df, price_col="close"))
        df = df.join(bollinger(df, price_col="close"))

    # Quick engineered columns
    if all(k in df.columns for k in ("high", "low", "close", "open")):
        df["close-open"] = df["close"].astype(float) - df["open"].astype(float)
        df["range"] = df["high"].astype(float) - df["low"].astype(float)

    # Bar-to-bar deltas (percent + log)
    b2t_pct_delta(
        df,
        cols=list(price_cols) + ["close-open"],
        extra_cols=["range"],
        round_places=6,
        direction="newest_top",
        open_col="open",
        close_col="close",
    )
    b2t_log_delta(
        df,
        cols=list(price_cols) + ["close-open"],
        extra_cols=["range"],
        prefix="_log_delta",
        round_places=6,
        add_intraday=True,
        open_col="open",
        close_col="close",
    )

    # Volatility (single-bar + rolling realized) via shims
    df = add_volatility_features(
        df,
        do_atr=True, do_parkinson=True, do_rs=True, do_gk=True,
        rolling_windows=tuple(returns_windows),
        direction="newest_top",
    )
    df = add_rolling_vol_from_returns_batch(
        df,
        price_col="close",
        modes=returns_modes,
        windows=tuple(returns_windows),
        annualize=True,
        direction="newest_top",
    )

    # EMAs + slopes
    base_cols = list(price_cols)
    add_ema_columns(df, base_cols, list(ema_windows))
    add_ema_d1(df, base_cols, list(ema_windows), direction="newest_top", overwrite=False, round_places=6)
    add_ema_d2(df, base_cols, list(ema_windows), direction="newest_top", overwrite=False, round_places=6)
    prepare_ema_helpers(df, base_cols, list(ema_windows), direction="newest_top", scale="bps")

    # Regime labels (close) and segments between EMA-slope sign flips
    _, labeled = compute_ema_comovement_stats(
        df.copy(),
        periods=list(ema_windows),
        direction="newest_top",
        close_col="close",
        return_col="close_pct_delta",
    )
    df["trend_state"] = labeled["regime_label"]

    segments, seg_summary, seg_by_year = build_flip_segments(
        df,
        base_cols=("close",),
        periods=list(ema_windows),
        direction="newest_top",
        scale="bps",
        date_col="timestamp",
        ema_name_fmt="{field}_ema_{period}",
    )

    major_stats, sub_stats, sub_stats_mixsum = compute_ema_comovement_hierarchy(
        df,
        periods=list(ema_windows),
        close_col="close",
        direction="newest_top",
        return_col="close_pct_delta",
    )

    summary = {
        "n_rows": int(len(df)),
        "n_segments": int(len(segments)),
        "mean_seg_return": float(segments["ret_close_to_close"].mean()) if len(segments) else 0.0,
        "mean_seg_len": float(segments["bars"].mean()) if len(segments) else 0.0,
    }
    return {
        "data": df,
        "segments": segments,
        "segment_summary": seg_summary,
        "segment_by_year": seg_by_year,
        "regime_major": major_stats,
        "regime_sub": sub_stats_mixsum,
        "summary": summary,
    }
