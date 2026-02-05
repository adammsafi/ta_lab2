# -*- coding: utf-8 -*-
"""
Created on Sat Dec 27 15:34:40 2025

@author: asafi
"""

import pandas as pd
from sqlalchemy import create_engine
from ta_lab2.config import TARGET_DB_URL

engine = create_engine(TARGET_DB_URL)
sessions = pd.read_sql(
    """
    SELECT asset_class, region, venue, asset_key_type, asset_key, session_type, timezone,
           session_open_local, session_close_local, is_24h
    FROM public.dim_sessions
    ORDER BY asset_class, region, venue, asset_key_type, asset_key, session_type
    LIMIT 50
    """,
    engine,
)
sessions
