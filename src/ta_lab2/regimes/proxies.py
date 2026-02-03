# src/ta_lab2/regimes/proxies.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
import pandas as pd


@dataclass
class ProxyInputs:
    child_daily: pd.DataFrame
    parent_weekly: Optional[
        pd.DataFrame
    ] = None  # e.g., NDX/sector/BTC weekly with precomputed EMAs/ATR
    market_weekly: Optional[
        pd.DataFrame
    ] = None  # broad market weekly (SPX/Total Market)


@dataclass
class ProxyOutcome:
    l0_cap: float = 1.0
    l1_size_mult: float = 1.0


def _is_weekly_up_normal(weekly: pd.DataFrame) -> bool:
    cols = weekly.columns
    if {"close", "close_ema_20", "close_ema_50", "close_ema_200"}.issubset(cols):
        up = (weekly["close"].iloc[-1] > weekly["close_ema_200"].iloc[-1]) and (
            weekly["close_ema_20"].iloc[-1] > weekly["close_ema_50"].iloc[-1]
        )
        return bool(up)
    return False


def infer_cycle_proxy(inp: ProxyInputs) -> ProxyOutcome:
    """
    If the asset lacks L0 history, use a broad market proxy to *tighten* net exposure caps.
    """
    out = ProxyOutcome()
    if inp.market_weekly is None or inp.market_weekly.empty:
        return out  # no change
    if not _is_weekly_up_normal(inp.market_weekly):
        out.l0_cap = 0.7  # cap net if market not supportive
    return out


def infer_weekly_macro_proxy(inp: ProxyInputs) -> ProxyOutcome:
    """
    If child has <52 weekly bars, borrow the parent regime to *tighten* size.
    """
    out = ProxyOutcome()
    w = inp.parent_weekly
    if w is None or w.empty:
        return out
    if not _is_weekly_up_normal(w):
        out.l1_size_mult = 0.7
    return out
