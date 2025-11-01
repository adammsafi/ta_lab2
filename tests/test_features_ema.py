import pandas as pd
from ta_lab2.features.ema import compute_ema  # adjust to your actual function name

def test_compute_ema_basic():
    s = pd.Series([1, 2, 3, 4, 5])
    out = compute_ema(s, window=3)  # example signature
    assert len(out) == 5
    assert pd.notna(out.iloc[-1])
