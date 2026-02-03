"""Economic data integration for ta_lab2.

Provides standardized access to economic data from various sources
(FRED, Fed, etc.) with consistent interfaces, optional caching,
rate limiting, and data quality validation.

Providers:
    FredProvider: Federal Reserve Economic Data (requires fredapi)

Install dependencies:
    pip install ta_lab2[fred]       # For FRED only
    pip install ta_lab2[economic]   # For all economic data providers

Example:
    >>> from ta_lab2.integrations.economic import FredProvider
    >>> provider = FredProvider()  # Uses FRED_API_KEY env var
    >>> result = provider.get_series("FEDFUNDS")
    >>> if result.success:
    ...     print(f"Federal Funds Rate: {result.series.data.iloc[-1]:.2f}%")

Types:
    EconomicSeries: Standardized time series data container
    FetchResult: Result wrapper with success/error status
    SeriesInfo: Series metadata without data

Base Classes:
    EconomicDataProvider: Abstract protocol for data providers

See Also:
    .archive/external-packages/2026-02-03/ALTERNATIVES.md - Ecosystem comparison
    ta_lab2.utils.economic - Extracted utilities from fedtools2
"""

from ta_lab2.integrations.economic.types import (
    EconomicSeries,
    FetchResult,
    SeriesInfo,
    FRED_SERIES,
)
from ta_lab2.integrations.economic.base import EconomicDataProvider
from ta_lab2.integrations.economic.fred_provider import (
    FredProvider,
    FREDAPI_AVAILABLE,
)

__all__ = [
    # Types
    "EconomicSeries",
    "FetchResult",
    "SeriesInfo",
    "FRED_SERIES",
    # Base
    "EconomicDataProvider",
    # Providers
    "FredProvider",
    "FREDAPI_AVAILABLE",
]
