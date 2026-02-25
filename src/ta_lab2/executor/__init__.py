"""Executor package: fill simulation, order routing, and paper trade execution."""

from ta_lab2.executor.fill_simulator import (
    FillResult,
    FillSimulator,
    FillSimulatorConfig,
)
from ta_lab2.executor.paper_executor import PaperExecutor
from ta_lab2.executor.position_sizer import (
    ExecutorConfig,
    PositionSizer,
    compute_order_delta,
)
from ta_lab2.executor.signal_reader import SignalReader, StaleSignalError

__all__ = [
    "FillResult",
    "FillSimulator",
    "FillSimulatorConfig",
    "PaperExecutor",
    "ExecutorConfig",
    "PositionSizer",
    "compute_order_delta",
    "SignalReader",
    "StaleSignalError",
]
