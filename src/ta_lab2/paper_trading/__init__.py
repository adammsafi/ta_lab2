"""
Paper trading package.

Provides CanonicalOrder (exchange format translation) and PaperOrderLogger
(paper_orders table persistence) for paper trading simulation.
"""

from .canonical_order import CanonicalOrder

__all__ = ["CanonicalOrder"]
