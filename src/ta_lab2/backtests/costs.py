"""
Cost model helpers shared by runners.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List


@dataclass
class CostModel:
    fee_bps: float = 0.0  # commission per trade in bps of notional
    slippage_bps: float = 0.0  # price slippage in bps
    funding_bps_day: float = 0.0  # daily funding cost in bps of absolute position

    def to_vbt_kwargs(self) -> Dict[str, Any]:
        return {
            "fees": self.fee_bps / 1e4,
            "slippage": self.slippage_bps / 1e4,
        }

    def describe(self) -> str:
        return f"fee={self.fee_bps:.2f}bps, slip={self.slippage_bps:.2f}bps, funding/day={self.funding_bps_day:.2f}bps"


# ---------------------------------------------------------------------------
# Kraken cost matrix: 6 spot + 6 perps = 12 scenarios
# Spot:  maker 0.16% (16 bps) x 3 slippage + taker 0.26% (26 bps) x 3 slippage
# Perps: same fees + funding 0.01%/8h = 0.03% per day (3 bps/day) x 6 fee/slip combos
# ---------------------------------------------------------------------------
_KRAKEN_SLIPPAGE_LEVELS = [5.0, 10.0, 20.0]  # bps
_SPOT_MAKER_FEE_BPS = 16.0  # Kraken spot maker fee: 0.16% = 16 bps
_SPOT_TAKER_FEE_BPS = 26.0  # Kraken spot taker fee: 0.26% = 26 bps
_PERPS_MAKER_FEE_BPS = 2.0  # Kraken perps maker fee: 0.02% = 2 bps
_PERPS_TAKER_FEE_BPS = 5.0  # Kraken perps taker fee: 0.05% = 5 bps
_PERPS_FUNDING_BPS_DAY = 3.0  # 0.01%/8h * 3 = 0.03%/day = 3 bps/day

KRAKEN_COST_MATRIX: List[CostModel] = (
    [
        # Spot maker scenarios (3): maker 16 bps x slippage 5/10/20
        CostModel(fee_bps=_SPOT_MAKER_FEE_BPS, slippage_bps=slip, funding_bps_day=0.0)
        for slip in _KRAKEN_SLIPPAGE_LEVELS
    ]
    + [
        # Spot taker scenarios (3): taker 26 bps x slippage 5/10/20
        CostModel(fee_bps=_SPOT_TAKER_FEE_BPS, slippage_bps=slip, funding_bps_day=0.0)
        for slip in _KRAKEN_SLIPPAGE_LEVELS
    ]
    + [
        # Perps maker scenarios (3): maker 2 bps + funding x slippage 5/10/20
        CostModel(
            fee_bps=_PERPS_MAKER_FEE_BPS,
            slippage_bps=slip,
            funding_bps_day=_PERPS_FUNDING_BPS_DAY,
        )
        for slip in _KRAKEN_SLIPPAGE_LEVELS
    ]
    + [
        # Perps taker scenarios (3): taker 5 bps + funding x slippage 5/10/20
        CostModel(
            fee_bps=_PERPS_TAKER_FEE_BPS,
            slippage_bps=slip,
            funding_bps_day=_PERPS_FUNDING_BPS_DAY,
        )
        for slip in _KRAKEN_SLIPPAGE_LEVELS
    ]
)

# ---------------------------------------------------------------------------
# Hyperliquid perps cost matrix: 6 scenarios (maker/taker x 3 slippage)
# Maker 0.015% (1.5 bps), Taker 0.045% (4.5 bps), HL CLOB tighter spreads
# Funding: BTC avg Q3-2025 from Coinalyze = 2.91 bps/day
# ---------------------------------------------------------------------------
_HL_SLIPPAGE_LEVELS = [3.0, 5.0, 10.0]  # bps -- HL CLOB has tighter spreads
_HL_TAKER_FEE_BPS = 4.5  # Base tier taker 0.045%
_HL_MAKER_FEE_BPS = 1.5  # Base tier maker 0.015%
_HL_FUNDING_BPS_DAY = 2.91  # BTC avg Q3-2025 (Coinalyze)

HYPERLIQUID_COST_MATRIX: List[CostModel] = [
    # HL maker scenarios (3): maker 1.5 bps x slippage 3/5/10
    CostModel(
        fee_bps=_HL_MAKER_FEE_BPS,
        slippage_bps=slip,
        funding_bps_day=_HL_FUNDING_BPS_DAY,
    )
    for slip in _HL_SLIPPAGE_LEVELS
] + [
    # HL taker scenarios (3): taker 4.5 bps x slippage 3/5/10
    CostModel(
        fee_bps=_HL_TAKER_FEE_BPS,
        slippage_bps=slip,
        funding_bps_day=_HL_FUNDING_BPS_DAY,
    )
    for slip in _HL_SLIPPAGE_LEVELS
]

# ---------------------------------------------------------------------------
# Lean cost matrix: 3 representative costs spanning the full range
# For fast screening (Pass 1) before deep 18-cost analysis (Pass 2)
# ---------------------------------------------------------------------------
LEAN_COST_MATRIX: List[CostModel] = [
    # Low cost: HL maker + tight spread (7.41 bps total)
    CostModel(
        fee_bps=_HL_MAKER_FEE_BPS,
        slippage_bps=3.0,
        funding_bps_day=_HL_FUNDING_BPS_DAY,
    ),
    # Mid cost: Kraken spot maker + medium slip (26 bps total)
    CostModel(fee_bps=_SPOT_MAKER_FEE_BPS, slippage_bps=10.0, funding_bps_day=0.0),
    # High cost: Kraken spot taker + wide slip (46 bps total)
    CostModel(fee_bps=_SPOT_TAKER_FEE_BPS, slippage_bps=20.0, funding_bps_day=0.0),
]

# ---------------------------------------------------------------------------
# Registry: maps exchange name -> cost matrix for multi-exchange bake-offs
# ---------------------------------------------------------------------------
COST_MATRIX_REGISTRY: Dict[str, List[CostModel]] = {
    "kraken": KRAKEN_COST_MATRIX,
    "hyperliquid": HYPERLIQUID_COST_MATRIX,
    "lean": LEAN_COST_MATRIX,
}
