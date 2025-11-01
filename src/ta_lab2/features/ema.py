
import pandas as pd
import numpy as np

def add_ema_columns(df: pd.DataFrame, fields, periods, suffix_fmt="{field}_ema_{period}"):
    for field in fields:
        x = df[field].astype(float)
        for p in periods:
            df[suffix_fmt.format(field=field, period=p)] = x.ewm(span=p, adjust=False).mean()
    return df

def add_ema_d1(df: pd.DataFrame, fields, periods, round_places=None, suffix_fmt="{field}_ema_{period}"):
    for field in fields:
        for p in periods:
            col = suffix_fmt.format(field=field, period=p)
            d1 = df[col].diff()
            if round_places is not None:
                d1 = d1.round(round_places)
            df[f"{col}_d1"] = d1
    return df

def add_ema_d2(df: pd.DataFrame, fields, periods, round_places=None, suffix_fmt="{field}_ema_{period}"):
    for field in fields:
        for p in periods:
            col = suffix_fmt.format(field=field, period=p)
            d2 = df[col].diff().diff()
            if round_places is not None:
                d2 = d2.round(round_places)
            df[f"{col}_d2"] = d2
    return df
