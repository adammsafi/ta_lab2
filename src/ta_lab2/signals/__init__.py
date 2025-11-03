# -*- coding: utf-8 -*-
"""
Signal package initializer for ta_lab2.

Exports:
    - generate_signals: master function for building trading signals.
    - basic EMA/RSI/ATR rule primitives for reuse in pipelines and testing.
"""

from .generator import generate_signals, attach_signals_from_config
from . import rules
