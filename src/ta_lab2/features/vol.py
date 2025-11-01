
import pandas as pd
import numpy as np

def add_atr(df: pd.DataFrame, period: int = 14,
            high_col="high", low_col="low", close_col="close"):
    high = df[high_col].astype(float)
    low  = df[low_col].astype(float)
    close = df[close_col].astype(float)
    prev_close = close.shift(1)
    tr = (high - low).abs()
    tr = np.maximum(tr, (high - prev_close).abs())
    tr = np.maximum(tr, (low - prev_close).abs())
    df[f"atr_{period}"] = tr.ewm(alpha=1/period, adjust=False).mean()
    return df
