"""
Paper-trade executor package (Phase 45).

Provides the complete signal-to-fill pipeline for paper trading:
- PaperExecutor: main orchestrator
- FillSimulator: slippage model (zero, fixed, lognormal)
- SignalReader: watermark-based signal deduplication
- PositionSizer: 3 sizing modes (fixed_fraction, regime_adjusted, signal_strength)
- ParityChecker: backtest parity verification
"""

from ta_lab2.executor.fill_simulator import (
    FillResult,
    FillSimulator,
    FillSimulatorConfig,
)
from ta_lab2.executor.parity_checker import ParityChecker
from ta_lab2.executor.paper_executor import PaperExecutor
from ta_lab2.executor.position_sizer import (
    ExecutorConfig,
    PositionSizer,
    compute_order_delta,
    REGIME_MULTIPLIERS,
)
from ta_lab2.executor.signal_reader import (
    SignalReader,
    StaleSignalError,
    SIGNAL_TABLE_MAP,
)

__all__ = [
    "PaperExecutor",
    "FillSimulator",
    "FillSimulatorConfig",
    "FillResult",
    "SignalReader",
    "StaleSignalError",
    "SIGNAL_TABLE_MAP",
    "PositionSizer",
    "ExecutorConfig",
    "compute_order_delta",
    "REGIME_MULTIPLIERS",
    "ParityChecker",
]
