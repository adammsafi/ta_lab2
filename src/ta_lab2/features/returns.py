
import pandas as pd
import numpy as np

def add_returns(df: pd.DataFrame, close_col="close"):
    df["ret"] = df[close_col].pct_change()
    df["logret"] = np.log(df[close_col]).diff()
    return df
