import pandas as pd
from fedtools2.utils.consolidation import combine_timeframes, missing_ranges

def test_missing_ranges_basic():
    idx = pd.date_range("2020-01-01", periods=5, freq="D")
    mask = pd.Series([False, True, True, False, True], index=idx)
    gaps = missing_ranges(mask)
    assert gaps == [(idx[1], idx[2]), (idx[4], idx[4])]