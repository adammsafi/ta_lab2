"""ta_lab2.macro -- FRED macro feature computation and regime classification.

Public API:
    load_series_wide          -- Read fred.series_values, pivot to wide DataFrame
    forward_fill_with_limits  -- Forward-fill with per-frequency limits + provenance
    compute_macro_features    -- Full pipeline: load -> ffill -> derive -> rename
    MacroRegimeClassifier     -- Rule-based 4-dimension macro regime labeler (Phase 67)
    load_macro_regime_config  -- Load YAML config for macro regime classifier
    HMMClassifier             -- GaussianHMM secondary classifier with BIC selection (Phase 68)
    LeadLagAnalyzer           -- Macro-to-crypto lead-lag cross-correlation analyzer (Phase 68)
    TransitionProbMatrix      -- Static + rolling regime transition probability matrices (Phase 68)
    get_transition_prob       -- Query any regime-to-regime transition probability (Phase 68)

Phase 65: FRED Table & Core Features
Phase 67: Macro Regime Classifier
Phase 68: HMM & Macro Analytics
"""

from ta_lab2.macro.feature_computer import compute_macro_features
from ta_lab2.macro.forward_fill import forward_fill_with_limits
from ta_lab2.macro.fred_reader import load_series_wide
from ta_lab2.macro.hmm_classifier import HMMClassifier
from ta_lab2.macro.lead_lag_analyzer import LeadLagAnalyzer
from ta_lab2.macro.regime_classifier import (
    MacroRegimeClassifier,
    load_macro_regime_config,
)
from ta_lab2.macro.transition_probs import TransitionProbMatrix, get_transition_prob

__all__ = [
    "load_series_wide",
    "forward_fill_with_limits",
    "compute_macro_features",
    "MacroRegimeClassifier",
    "load_macro_regime_config",
    "HMMClassifier",
    "LeadLagAnalyzer",
    "TransitionProbMatrix",
    "get_transition_prob",
]
