"""Base protocol for economic data providers.

Defines the interface that all economic data providers must implement,
enabling consistent usage across different data sources (FRED, Fed, etc.).
"""
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional, List

from ta_lab2.integrations.economic.types import EconomicSeries, FetchResult, SeriesInfo


class EconomicDataProvider(ABC):
    """Abstract base class for economic data providers.

    All providers must implement the core methods for fetching series data
    and metadata. Optional methods for search and batch operations have
    default implementations.

    Attributes:
        name: Provider name (e.g., "FRED", "Fed")
        base_url: API base URL

    Example:
        >>> class MyProvider(EconomicDataProvider):
        ...     name = "MySource"
        ...     def get_series(self, series_id, **kwargs):
        ...         # Implementation
        ...         pass
        ...     def get_series_info(self, series_id):
        ...         # Implementation
        ...         pass
    """
    name: str = "Unknown"
    base_url: str = ""

    @abstractmethod
    def get_series(
        self,
        series_id: str,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        **kwargs
    ) -> FetchResult:
        """Fetch time series data for a given series ID.

        Args:
            series_id: Unique identifier for the series (e.g., "FEDFUNDS")
            start_date: Optional start date filter
            end_date: Optional end date filter
            **kwargs: Provider-specific options

        Returns:
            FetchResult with success status and data or error
        """
        pass

    @abstractmethod
    def get_series_info(self, series_id: str) -> Optional[SeriesInfo]:
        """Fetch metadata about a series without the data.

        Args:
            series_id: Unique identifier for the series

        Returns:
            SeriesInfo with metadata, or None if not found
        """
        pass

    def search(self, query: str, limit: int = 10) -> List[SeriesInfo]:
        """Search for series by keyword.

        Default implementation returns empty list. Override for providers
        that support search (e.g., FRED).

        Args:
            query: Search query string
            limit: Maximum number of results

        Returns:
            List of matching SeriesInfo objects
        """
        return []

    def get_multiple_series(
        self,
        series_ids: List[str],
        **kwargs
    ) -> List[FetchResult]:
        """Fetch multiple series.

        Default implementation calls get_series sequentially.
        Override for providers that support batch fetching.

        Args:
            series_ids: List of series IDs to fetch
            **kwargs: Options passed to get_series

        Returns:
            List of FetchResult objects
        """
        return [self.get_series(sid, **kwargs) for sid in series_ids]

    def validate_api_key(self) -> bool:
        """Check if the provider's API key is valid.

        Default implementation returns True. Override for providers
        that require authentication.

        Returns:
            True if API key is valid or not required
        """
        return True

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}(name={self.name})>"
