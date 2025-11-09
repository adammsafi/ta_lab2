"""
Cost model helpers shared by runners.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, Any


@dataclass
class CostModel:
    fee_bps: float = 0.0         # commission per trade in bps of notional
    slippage_bps: float = 0.0    # price slippage in bps
    funding_bps_day: float = 0.0 # daily funding cost in bps of absolute position

    def to_vbt_kwargs(self) -> Dict[str, Any]:
        return {
            "fees": self.fee_bps / 1e4,
            "slippage": self.slippage_bps / 1e4,
        }

    def describe(self) -> str:
        return f"fee={self.fee_bps:.2f}bps, slip={self.slippage_bps:.2f}bps, funding/day={self.funding_bps_day:.2f}bps"
