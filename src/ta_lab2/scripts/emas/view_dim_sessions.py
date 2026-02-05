# -*- coding: utf-8 -*-
"""
Created on Sat Dec 27 15:36:03 2025

@author: asafi
"""

from datetime import date
from ta_lab2.time.dim_sessions import DimSessions, SessionKey

ds = DimSessions.from_db()

key = SessionKey(
    asset_class="EQ",
    region="US",
    venue="US_EQUITIES",
    asset_key_type="CUSIP",
    asset_key="023135106",
    session_type="PRIMARY",
)

win = ds.session_windows_utc_by_key(
    key=key,
    start_date=date(2025, 3, 1),
    end_date=date(2025, 3, 15),
)

win[["session_date", "timezone", "session_open_local", "open_utc", "close_utc"]].head(
    10
)
