# src/ta_lab2/time/__init__.py
"""
Time and timeframe utilities for ta_lab2.

This package centralizes:
- dim_timeframe access (timeframe metadata, alignment, anchors)
- (later) session metadata (dim_sessions)
- any shared time/calendar helpers
"""

from .dim_timeframe import DimTimeframe, TFMeta
from .dim_sessions import DimSessions, SessionMeta

__all__ = ["DimTimeframe", "TFMeta", "DimSessions", "SessionMeta"]
