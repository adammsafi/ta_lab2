
import pandas as pd
from .resample import bin_by_calendar, bin_by_season
from .features.ema import add_ema_columns, add_ema_d1, add_ema_d2
from .features.calendar import expand_datetime_features_inplace

def prep_for_stats(df, time_col="period_end", newest_first=True):
    w = df.rename(columns={time_col: "date"})
    if newest_first:
        w = w.sort_values("date", ascending=False).reset_index(drop=True)
    return w

def build_timeframe(symbol: str, base_daily: pd.DataFrame, tf: str, dt_col="timeopen"):
    if tf == "1D":
        bars = base_daily.rename(columns={dt_col:"date"}).copy()
        bars["timeframe"] = "1D"
    elif tf == "1W":
        bars = bin_by_calendar(base_daily, dt_col, "W-SUN").rename(columns={"period_end":"date"})
        bars["timeframe"] = "1W"
    elif tf == "1M":
        bars = bin_by_calendar(base_daily, dt_col, "MS").rename(columns={"period_end":"date"})
        bars["timeframe"] = "1M"
    else:
        raise ValueError("Add tf as needed (e.g., seasons, quarters, years).")
    bars["symbol"] = symbol
    prices = bars[["date","symbol","timeframe","open","high","low","close","volume"]].copy()

    cal = prices[["date"]].drop_duplicates().copy()
    expand_datetime_features_inplace(cal, "date", prefix="date")  # adds seasons/moon (if available)
    cal["symbol"] = symbol; cal["timeframe"] = prices["timeframe"].iloc[0]

    ema = prices[["date","symbol","timeframe","close"]].copy()
    add_ema_columns(ema, ["close"], [21,50,100,200])
    add_ema_d1(ema, ["close"], [21,50,100,200])
    add_ema_d2(ema, ["close"], [21,50,100,200])
    return dict(prices=prices, calendar=cal, ema=ema)
