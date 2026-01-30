"""
Backtest execution from stored signals.

This module provides backtesting infrastructure that reads signals from database
tables and executes backtests using vectorbt. Results are stored in the database
for reproducibility tracking and historical analysis.

Key components:
- SignalBacktester: Main class for running backtests from signals
- BacktestResult: Dataclass holding backtest results
"""

from .backtest_from_signals import SignalBacktester, BacktestResult

__all__ = ["SignalBacktester", "BacktestResult"]
