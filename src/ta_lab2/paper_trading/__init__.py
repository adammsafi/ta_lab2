"""
Paper trading package.

Provides CanonicalOrder (exchange format translation) and PaperOrderLogger
(paper_orders table persistence) for paper trading simulation.
"""

from .canonical_order import CanonicalOrder
from .paper_order_logger import PaperOrderLogger

__all__ = ["CanonicalOrder", "PaperOrderLogger"]
