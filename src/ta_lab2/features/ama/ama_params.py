"""
AMA Parameter Management.

Defines canonical parameter sets for all AMA indicators (KAMA, DEMA, TEMA, HMA)
as frozen module-level constants, along with parameter hashing utilities.

CRITICAL: Parameter dicts are frozen once in production. Changing dict keys changes
the params_hash and orphans historical data in cmc_ama_multi_tf.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field


# =============================================================================
# Parameter Hashing
# =============================================================================


def compute_params_hash(params: dict) -> str:
    """
    Compute stable MD5 hash of a params dict.

    Keys are sorted for canonicality. Returns a 32-character hex string.
    This hash is used as a PK discriminator in cmc_ama_multi_tf — changing
    the dict structure (keys or values) changes the hash and orphans historical rows.

    Args:
        params: Indicator parameters dict (e.g. {"er_period": 10, "fast_period": 2, ...})

    Returns:
        32-character lowercase hex MD5 string.

    Examples:
        >>> h1 = compute_params_hash({"er_period": 10, "fast_period": 2, "slow_period": 30})
        >>> h2 = compute_params_hash({"slow_period": 30, "er_period": 10, "fast_period": 2})
        >>> h1 == h2
        True
    """
    canonical = json.dumps(params, sort_keys=True, separators=(",", ":"))
    return hashlib.md5(canonical.encode()).hexdigest()


# =============================================================================
# AMAParamSet Dataclass
# =============================================================================


@dataclass(frozen=True)
class AMAParamSet:
    """
    Frozen descriptor for a single AMA indicator + parameter combination.

    Fields:
        indicator: Indicator name ("KAMA", "DEMA", "TEMA", or "HMA").
        params: Canonical params dict. NEVER modify after construction.
        params_hash: MD5 of the canonical params dict (computed at definition time).
        label: Human-readable label for display (e.g. "KAMA(10,2,30)").
        warmup: Minimum bars before first valid value is produced.
    """

    indicator: str
    params: dict = field(hash=False, compare=False)
    params_hash: str
    label: str
    warmup: int


# =============================================================================
# Warmup Helper
# =============================================================================


def get_warmup(indicator: str, params: dict) -> int:
    """
    Return the warmup threshold (minimum bars) for the given indicator and params.

    Rows below this threshold produce NULL (NaN) in AMA computation.

    Args:
        indicator: One of "KAMA", "DEMA", "TEMA", "HMA".
        params: The canonical params dict for the indicator.

    Returns:
        Integer warmup count.

    Raises:
        ValueError: If indicator is not recognised.
    """
    indicator = indicator.upper()
    if indicator == "KAMA":
        return params["er_period"]
    elif indicator == "DEMA":
        return 2 * params["period"] - 1
    elif indicator == "TEMA":
        return 3 * params["period"] - 1
    elif indicator == "HMA":
        return params["period"] + int(params["period"] ** 0.5) - 2
    else:
        raise ValueError(
            f"Unknown indicator '{indicator}'. Expected KAMA, DEMA, TEMA, or HMA."
        )


# =============================================================================
# KAMA Parameter Dicts (canonical — never construct inline at call sites)
# =============================================================================

_KAMA_CANONICAL_PARAMS = {"er_period": 10, "fast_period": 2, "slow_period": 30}
_KAMA_FAST_PARAMS = {"er_period": 5, "fast_period": 2, "slow_period": 15}
_KAMA_SLOW_PARAMS = {"er_period": 20, "fast_period": 2, "slow_period": 50}

# =============================================================================
# KAMA Parameter Sets
# =============================================================================

KAMA_CANONICAL = AMAParamSet(
    indicator="KAMA",
    params=_KAMA_CANONICAL_PARAMS,
    params_hash=compute_params_hash(_KAMA_CANONICAL_PARAMS),
    label="KAMA(10,2,30)",
    warmup=get_warmup("KAMA", _KAMA_CANONICAL_PARAMS),
)

KAMA_FAST = AMAParamSet(
    indicator="KAMA",
    params=_KAMA_FAST_PARAMS,
    params_hash=compute_params_hash(_KAMA_FAST_PARAMS),
    label="KAMA(5,2,15)",
    warmup=get_warmup("KAMA", _KAMA_FAST_PARAMS),
)

KAMA_SLOW = AMAParamSet(
    indicator="KAMA",
    params=_KAMA_SLOW_PARAMS,
    params_hash=compute_params_hash(_KAMA_SLOW_PARAMS),
    label="KAMA(20,2,50)",
    warmup=get_warmup("KAMA", _KAMA_SLOW_PARAMS),
)

# =============================================================================
# DEMA Parameter Dicts and Sets  (period is the only param)
# =============================================================================

_DEMA_PARAMS_9 = {"period": 9}
_DEMA_PARAMS_10 = {"period": 10}
_DEMA_PARAMS_21 = {"period": 21}
_DEMA_PARAMS_50 = {"period": 50}
_DEMA_PARAMS_200 = {"period": 200}

DEMA_9 = AMAParamSet(
    indicator="DEMA",
    params=_DEMA_PARAMS_9,
    params_hash=compute_params_hash(_DEMA_PARAMS_9),
    label="DEMA(9)",
    warmup=get_warmup("DEMA", _DEMA_PARAMS_9),
)

DEMA_10 = AMAParamSet(
    indicator="DEMA",
    params=_DEMA_PARAMS_10,
    params_hash=compute_params_hash(_DEMA_PARAMS_10),
    label="DEMA(10)",
    warmup=get_warmup("DEMA", _DEMA_PARAMS_10),
)

DEMA_21 = AMAParamSet(
    indicator="DEMA",
    params=_DEMA_PARAMS_21,
    params_hash=compute_params_hash(_DEMA_PARAMS_21),
    label="DEMA(21)",
    warmup=get_warmup("DEMA", _DEMA_PARAMS_21),
)

DEMA_50 = AMAParamSet(
    indicator="DEMA",
    params=_DEMA_PARAMS_50,
    params_hash=compute_params_hash(_DEMA_PARAMS_50),
    label="DEMA(50)",
    warmup=get_warmup("DEMA", _DEMA_PARAMS_50),
)

DEMA_200 = AMAParamSet(
    indicator="DEMA",
    params=_DEMA_PARAMS_200,
    params_hash=compute_params_hash(_DEMA_PARAMS_200),
    label="DEMA(200)",
    warmup=get_warmup("DEMA", _DEMA_PARAMS_200),
)

# =============================================================================
# TEMA Parameter Dicts and Sets
# =============================================================================

_TEMA_PARAMS_9 = {"period": 9}
_TEMA_PARAMS_10 = {"period": 10}
_TEMA_PARAMS_21 = {"period": 21}
_TEMA_PARAMS_50 = {"period": 50}
_TEMA_PARAMS_200 = {"period": 200}

TEMA_9 = AMAParamSet(
    indicator="TEMA",
    params=_TEMA_PARAMS_9,
    params_hash=compute_params_hash(_TEMA_PARAMS_9),
    label="TEMA(9)",
    warmup=get_warmup("TEMA", _TEMA_PARAMS_9),
)

TEMA_10 = AMAParamSet(
    indicator="TEMA",
    params=_TEMA_PARAMS_10,
    params_hash=compute_params_hash(_TEMA_PARAMS_10),
    label="TEMA(10)",
    warmup=get_warmup("TEMA", _TEMA_PARAMS_10),
)

TEMA_21 = AMAParamSet(
    indicator="TEMA",
    params=_TEMA_PARAMS_21,
    params_hash=compute_params_hash(_TEMA_PARAMS_21),
    label="TEMA(21)",
    warmup=get_warmup("TEMA", _TEMA_PARAMS_21),
)

TEMA_50 = AMAParamSet(
    indicator="TEMA",
    params=_TEMA_PARAMS_50,
    params_hash=compute_params_hash(_TEMA_PARAMS_50),
    label="TEMA(50)",
    warmup=get_warmup("TEMA", _TEMA_PARAMS_50),
)

TEMA_200 = AMAParamSet(
    indicator="TEMA",
    params=_TEMA_PARAMS_200,
    params_hash=compute_params_hash(_TEMA_PARAMS_200),
    label="TEMA(200)",
    warmup=get_warmup("TEMA", _TEMA_PARAMS_200),
)

# =============================================================================
# HMA Parameter Dicts and Sets
# =============================================================================

_HMA_PARAMS_9 = {"period": 9}
_HMA_PARAMS_10 = {"period": 10}
_HMA_PARAMS_21 = {"period": 21}
_HMA_PARAMS_50 = {"period": 50}
_HMA_PARAMS_200 = {"period": 200}

HMA_9 = AMAParamSet(
    indicator="HMA",
    params=_HMA_PARAMS_9,
    params_hash=compute_params_hash(_HMA_PARAMS_9),
    label="HMA(9)",
    warmup=get_warmup("HMA", _HMA_PARAMS_9),
)

HMA_10 = AMAParamSet(
    indicator="HMA",
    params=_HMA_PARAMS_10,
    params_hash=compute_params_hash(_HMA_PARAMS_10),
    label="HMA(10)",
    warmup=get_warmup("HMA", _HMA_PARAMS_10),
)

HMA_21 = AMAParamSet(
    indicator="HMA",
    params=_HMA_PARAMS_21,
    params_hash=compute_params_hash(_HMA_PARAMS_21),
    label="HMA(21)",
    warmup=get_warmup("HMA", _HMA_PARAMS_21),
)

HMA_50 = AMAParamSet(
    indicator="HMA",
    params=_HMA_PARAMS_50,
    params_hash=compute_params_hash(_HMA_PARAMS_50),
    label="HMA(50)",
    warmup=get_warmup("HMA", _HMA_PARAMS_50),
)

HMA_200 = AMAParamSet(
    indicator="HMA",
    params=_HMA_PARAMS_200,
    params_hash=compute_params_hash(_HMA_PARAMS_200),
    label="HMA(200)",
    warmup=get_warmup("HMA", _HMA_PARAMS_200),
)

# =============================================================================
# Convenience Collections
# =============================================================================

ALL_KAMA_PARAMS: list[AMAParamSet] = [KAMA_CANONICAL, KAMA_FAST, KAMA_SLOW]

ALL_DEMA_PARAMS: list[AMAParamSet] = [DEMA_9, DEMA_10, DEMA_21, DEMA_50, DEMA_200]

ALL_TEMA_PARAMS: list[AMAParamSet] = [TEMA_9, TEMA_10, TEMA_21, TEMA_50, TEMA_200]

ALL_HMA_PARAMS: list[AMAParamSet] = [HMA_9, HMA_10, HMA_21, HMA_50, HMA_200]

ALL_AMA_PARAMS: list[AMAParamSet] = (
    ALL_KAMA_PARAMS + ALL_DEMA_PARAMS + ALL_TEMA_PARAMS + ALL_HMA_PARAMS
)
