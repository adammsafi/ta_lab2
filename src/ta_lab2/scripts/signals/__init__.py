"""
Signal infrastructure - State management and utilities for signal generation.

This module provides state tracking for signal positions and utilities for
reproducibility (feature hashing, params hashing, signal configuration loading).

Exports:
    - SignalStateManager: State tracking for stateful signal positions
    - SignalStateConfig: Configuration for signal state management
    - compute_feature_hash: SHA256 hash of feature data for reproducibility
    - compute_params_hash: SHA256 hash of signal parameters
    - load_active_signals: Query active signals from dim_signals
"""

from .signal_state_manager import SignalStateManager, SignalStateConfig
from .signal_utils import (
    compute_feature_hash,
    compute_params_hash,
    load_active_signals,
)

__all__ = [
    "SignalStateManager",
    "SignalStateConfig",
    "compute_feature_hash",
    "compute_params_hash",
    "load_active_signals",
]
