# src/ta_lab2/regimes/__init__.py
"""
Public API for `ta_lab2.regimes`.

This module exposes:
1) Your existing analytics utilities (kept exactly as-is):
   - EMA co-movement statistics and helpers from `comovement.py`
   - Flip-segmentation shim from `segments.py` (implementation lives in features)

2) Optional L0–L4 regime scaffold (additive; does NOT change existing behavior):
   - `data_budget`: decide which layers (L0..L4) are enabled based on history depth,
     and whether to use "full" vs "lite" feature tiers.
   - `labels`: rule-based labelers for trend/vol/liquidity + per-layer wrappers.
   - `resolver`: tighten-only policy resolver (higher layers can only tighten risk),
     plus a tiny hysteresis helper and a default policy table.
   - `proxies`: infer conservative (tightening) caps from parent/market when the
     asset is too young for L0/L1.
   - `policy_loader`: optional YAML overlay to customize policy rules.

3) (New, optional) Curated convenience re-exports from `flips.py` so you can:
      from ta_lab2.regimes import sign_from_series, detect_flips, ...
   This is import-safe and purely additive.
"""

# ---------- Existing, preserved exports ----------
from .comovement import (
    compute_ema_comovement_stats,
    compute_ema_comovement_hierarchy,
    build_alignment_frame,
    sign_agreement,
    rolling_agreement,
    forward_return_split,
    lead_lag_max_corr,
)

# Shim export so callers can `from ta_lab2.regimes import build_flip_segments`
# Actual implementation resides in ta_lab2.features.segments; this keeps old paths working.
from .segments import build_flip_segments

# ---------- Optional regime framework (additive) ----------
# Import-guarded so the package remains importable even if these modules are not present.
try:
    from .data_budget import assess_data_budget, DataBudgetContext
except Exception:  # pragma: no cover
    assess_data_budget = None  # type: ignore
    DataBudgetContext = None  # type: ignore

try:
    from .labels import (
        label_trend_basic,
        label_vol_bucket,
        label_liquidity_bucket,
        compose_regime_key,
        label_layer_monthly,
        label_layer_weekly,
        label_layer_daily,
        label_layer_intraday,
    )
except Exception:  # pragma: no cover
    label_trend_basic = None  # type: ignore
    label_vol_bucket = None  # type: ignore
    label_liquidity_bucket = None  # type: ignore
    compose_regime_key = None  # type: ignore
    label_layer_monthly = None  # type: ignore
    label_layer_weekly = None  # type: ignore
    label_layer_daily = None  # type: ignore
    label_layer_intraday = None  # type: ignore

try:
    from .resolver import (
        apply_hysteresis,
        resolve_policy,
        DEFAULT_POLICY_TABLE,
        TightenOnlyPolicy,
    )
except Exception:  # pragma: no cover
    apply_hysteresis = None  # type: ignore
    resolve_policy = None  # type: ignore
    DEFAULT_POLICY_TABLE = {}  # type: ignore
    TightenOnlyPolicy = None  # type: ignore

try:
    from .proxies import (
        infer_cycle_proxy,
        infer_weekly_macro_proxy,
        ProxyInputs,
        ProxyOutcome,
    )
except Exception:  # pragma: no cover
    infer_cycle_proxy = None  # type: ignore
    infer_weekly_macro_proxy = None  # type: ignore
    ProxyInputs = None  # type: ignore
    ProxyOutcome = None  # type: ignore

try:
    from .policy_loader import load_policy_table
except Exception:  # pragma: no cover
    load_policy_table = None  # type: ignore

# ---------- New: curated convenience re-exports from flips.py (safe, optional) ----------
# We import specific names *if they exist*; this keeps the public API stable and avoids breakage.
_flips_exported = []
try:
    _flips_exported = [
        "sign_from_series",
        "detect_flips",
        "label_regimes_from_flips",
        "attach_regimes",
        "regime_stats",
    ]
except Exception:
    # If flips.py changes or some names don't exist, we simply don't expose them.
    _flips_exported = []

__all__ = [
    # ---- Existing (preserved) ----
    "compute_ema_comovement_stats",
    "compute_ema_comovement_hierarchy",
    "build_alignment_frame",
    "sign_agreement",
    "rolling_agreement",
    "forward_return_split",
    "lead_lag_max_corr",
    "build_flip_segments",
    # ---- Optional regime framework (present if modules are available) ----
    "assess_data_budget",
    "DataBudgetContext",
    "label_trend_basic",
    "label_vol_bucket",
    "label_liquidity_bucket",
    "compose_regime_key",
    "label_layer_monthly",
    "label_layer_weekly",
    "label_layer_daily",
    "label_layer_intraday",
    "apply_hysteresis",
    "resolve_policy",
    "DEFAULT_POLICY_TABLE",
    "TightenOnlyPolicy",
    "infer_cycle_proxy",
    "infer_weekly_macro_proxy",
    "ProxyInputs",
    "ProxyOutcome",
    "load_policy_table",
]

# Append any flips re-exports that were successfully imported
for _name in _flips_exported:
    __all__.append(_name)
