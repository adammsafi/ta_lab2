# src/ta_lab2/regimes/resolver.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, Mapping, Optional

# Small default policy table (can be externalized to YAML later)
DEFAULT_POLICY_TABLE: Dict[str, Dict[str, object]] = {
    # Keys are regime fragments; we match by simple contains() checks
    "Up-Normal-Normal": {"size_mult": 1.00, "stop_mult": 1.50, "setups": ["breakout","pullback"], "orders": "mixed"},
    "Up-Low-":          {"size_mult": 1.10, "stop_mult": 1.25, "setups": ["breakout","pullback"], "orders": "mixed"},
    "Up-High-":         {"size_mult": 0.75, "stop_mult": 1.75, "setups": ["pullback"], "orders": "conservative"},
    "Sideways-Low-":    {"size_mult": 0.70, "stop_mult": 1.25, "setups": ["mean_revert"], "orders": "passive"},
    "Sideways-High-":   {"size_mult": 0.40, "stop_mult": 2.00, "setups": ["stand_down","mean_revert"], "orders": "passive"},
    "Down-":            {"size_mult": 0.60, "stop_mult": 1.60, "setups": ["short_rallies","hedge"], "orders": "mixed"},
    "-Stressed":        {"size_mult": 0.60, "stop_mult": 1.25, "setups": None, "orders": "passive"},  # liquidity override
}

@dataclass
class TightenOnlyPolicy:
    size_mult: float = 1.0
    stop_mult: float = 1.5
    orders: str = "mixed"             # "mixed" | "passive" | "conservative"
    setups: Optional[list] = None     # list of allowed setups
    gross_cap: float = 1.0            # 1.0 = 100% notional cap
    pyramids: bool = True

def _match_policy(regime_key: str, table: Mapping[str, Mapping[str, object]]) -> Dict[str, object]:
    for k, v in table.items():
        # very lightweight pattern: all tokens in k must appear in regime_key
        tokens = [t for t in k.split("-") if t]  # ignore empty fragments
        if all(t in regime_key for t in tokens):
            return dict(v)
    # fallback
    return {"size_mult": 0.8, "stop_mult": 1.5, "setups": ["pullback"], "orders": "mixed"}

def apply_hysteresis(prev_key: Optional[str], new_key: str, *, min_change: int = 0) -> str:
    """
    Minimal form: if prev == new or min_change==0 -> accept.
    If you attach counters elsewhere, gate on them here.
    """
    return new_key if prev_key is None or min_change <= 0 or prev_key != new_key else prev_key

def _tighten(dst: TightenOnlyPolicy, src: Dict[str, object]) -> TightenOnlyPolicy:
    # Tighten-only semantics: size = min; stop = max; gross_cap = min; pyramids ANDed
    return TightenOnlyPolicy(
        size_mult=min(dst.size_mult, float(src.get("size_mult", dst.size_mult))),
        stop_mult=max(dst.stop_mult, float(src.get("stop_mult", dst.stop_mult))),
        orders=src.get("orders", dst.orders) if dst.orders != "passive" else "passive",
        setups=list(sorted(set(dst.setups or []) | set(src.get("setups") or []))) if src.get("setups") else (dst.setups or []),
        gross_cap=min(dst.gross_cap, float(src.get("gross_cap", dst.gross_cap))),
        pyramids=dst.pyramids and bool(src.get("pyramids", True)),
    )

def resolve_policy_from_table(
    policy_table: Mapping[str, Mapping[str, object]],
    *,
    L0: Optional[str] = None,
    L1: Optional[str] = None,
    L2: Optional[str] = None,
    L3: Optional[str] = None,
    L4: Optional[str] = None,
    base: Optional[TightenOnlyPolicy] = None,
) -> TightenOnlyPolicy:
    """
    Combine layer regimes into a single tighten-only policy using the provided policy_table.
    Higher layers can only tighten risk, never loosen it.
    """
    policy = base or TightenOnlyPolicy()
    # Start with meso (L2) tactics, then tighten by L1/L0; L3/L4 affect orders/liquidity
    for key in (L2, L1, L0, L3, L4):
        if key:
            policy = _tighten(policy, _match_policy(key, policy_table))
        if key and "Stressed" in key:
            policy.orders = "passive"
    return policy

def resolve_policy(
    *,
    L0: Optional[str] = None,
    L1: Optional[str] = None,
    L2: Optional[str] = None,
    L3: Optional[str] = None,
    L4: Optional[str] = None,
    base: Optional[TightenOnlyPolicy] = None,
) -> TightenOnlyPolicy:
    """
    Back-compat wrapper that uses the in-code DEFAULT_POLICY_TABLE.
    """
    return resolve_policy_from_table(
        DEFAULT_POLICY_TABLE,
        L0=L0, L1=L1, L2=L2, L3=L3, L4=L4, base=base
    )
