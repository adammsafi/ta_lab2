# tests/regimes/test_regime_labelers_feature_utils_smoke.py
import pandas as pd
from ta_lab2.regimes.feature_utils import ensure_regime_features
from ta_lab2.regimes import label_layer_daily, assess_data_budget


def test_daily_labeler_with_minimal_features_smoke():
    # build a tiny daily DF
    idx = pd.date_range("2024-01-01", periods=200, freq="D")
    price = pd.Series(100.0).reindex(idx).ffill()
    price = price + (pd.Series(range(len(idx)), index=idx) * 0.1)  # gentle up drift
    df = (
        pd.DataFrame({"close": price}, index=idx)
        .reset_index()
        .rename(columns={"index": "timestamp"})
    )
    df = df.set_index("timestamp")

    df = ensure_regime_features(df, tf="D")
    ctx = assess_data_budget(daily=df)
    lab = label_layer_daily(df, mode=ctx.feature_tier)
    assert lab.iloc[-1] in {
        "Up-Low-Normal",
        "Up-Normal-Normal",
        "Up-High-Normal",
        "Sideways-Low-Normal",
        "Sideways-Normal-Normal",
        "Down-Normal-Normal",
    }
