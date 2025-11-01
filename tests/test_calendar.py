# tests/test_calendar.py
import pandas as pd
from ta_lab2.features.calendar import expand_datetime_features_inplace
def test_calendar_expands():
    df = pd.DataFrame({"ts":["2025-01-01T00:00:00Z","2025-01-02T00:00:00Z"]})
    expand_datetime_features_inplace(df, "ts", prefix="ts", add_moon=False)
    assert {"ts_quarter","ts_week_of_year","ts_day_of_year"} <= set(df.columns)
