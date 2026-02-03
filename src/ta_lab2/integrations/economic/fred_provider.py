"""FRED data provider using fredapi.

Provides a working implementation of EconomicDataProvider that wraps
the fredapi library. Includes graceful degradation when fredapi is
not installed.

Install fredapi with: pip install ta_lab2[fred]
"""
import os
import time
from datetime import datetime
from typing import Optional, List

import pandas as pd

from ta_lab2.integrations.economic.base import EconomicDataProvider
from ta_lab2.integrations.economic.types import (
    EconomicSeries,
    FetchResult,
    SeriesInfo,
)

# Soft import: allow importing module even if fredapi is missing
try:
    from fredapi import Fred
    FREDAPI_AVAILABLE = True
except ImportError:
    Fred = None  # type: ignore
    FREDAPI_AVAILABLE = False


def _ensure_fredapi_available() -> None:
    """Raise clear error if fredapi is not installed."""
    if not FREDAPI_AVAILABLE:
        raise ImportError(
            "fredapi is required for FredProvider. "
            "Install with: pip install ta_lab2[fred] "
            "or: pip install fredapi>=0.5.2"
        )


class FredProvider(EconomicDataProvider):
    """FRED data provider using fredapi.

    Provides access to Federal Reserve Economic Data (FRED) via the
    fredapi library. Supports all standard FRED operations including
    series fetching, search, and metadata retrieval.

    Attributes:
        name: "FRED"
        base_url: "https://api.stlouisfed.org/fred"
        api_key: FRED API key (from constructor or environment)

    Example:
        >>> provider = FredProvider()  # Uses FRED_API_KEY env var
        >>> result = provider.get_series("FEDFUNDS")
        >>> if result.success:
        ...     print(f"Got {len(result.series.data)} observations")

    Note:
        Requires fredapi package: pip install ta_lab2[fred]
        Requires FRED API key: https://fred.stlouisfed.org/docs/api/api_key.html
    """
    name = "FRED"
    base_url = "https://api.stlouisfed.org/fred"

    def __init__(self, api_key: Optional[str] = None):
        """Initialize FRED provider.

        Args:
            api_key: FRED API key. If None, reads from FRED_API_KEY
                     environment variable.

        Raises:
            ImportError: If fredapi is not installed
            ValueError: If no API key provided or found in environment
        """
        _ensure_fredapi_available()

        self.api_key = api_key or os.getenv("FRED_API_KEY")
        if not self.api_key:
            raise ValueError(
                "FRED API key required. Set FRED_API_KEY environment variable "
                "or pass api_key to constructor. "
                "Get key at: https://fred.stlouisfed.org/docs/api/api_key.html"
            )

        self._client = Fred(api_key=self.api_key)

    def get_series(
        self,
        series_id: str,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        **kwargs
    ) -> FetchResult:
        """Fetch time series data from FRED.

        Args:
            series_id: FRED series ID (e.g., "FEDFUNDS", "UNRATE")
            start_date: Optional start date filter
            end_date: Optional end date filter
            **kwargs: Additional options (frequency, aggregation_method, units)

        Returns:
            FetchResult with EconomicSeries on success, error message on failure

        Example:
            >>> result = provider.get_series("UNRATE", start_date=datetime(2020, 1, 1))
            >>> if result.success:
            ...     print(result.series.data.tail())
        """
        start_time = time.time()

        try:
            # Fetch data from FRED
            data = self._client.get_series(
                series_id,
                observation_start=start_date,
                observation_end=end_date,
                **kwargs
            )

            # Get metadata
            info = self._client.get_series_info(series_id)

            # Build EconomicSeries
            series = EconomicSeries(
                series_id=series_id,
                title=info.get("title", series_id),
                data=data,
                units=info.get("units", "Unknown"),
                frequency=info.get("frequency", "Unknown"),
                source="FRED",
                last_updated=pd.to_datetime(info.get("last_updated")),
                metadata=dict(info)
            )

            return FetchResult(
                success=True,
                series=series,
                fetch_time_ms=(time.time() - start_time) * 1000
            )

        except Exception as e:
            return FetchResult(
                success=False,
                error=str(e),
                fetch_time_ms=(time.time() - start_time) * 1000
            )

    def get_series_info(self, series_id: str) -> Optional[SeriesInfo]:
        """Fetch metadata about a FRED series.

        Args:
            series_id: FRED series ID

        Returns:
            SeriesInfo with metadata, or None if not found
        """
        try:
            info = self._client.get_series_info(series_id)
            return SeriesInfo(
                series_id=series_id,
                title=info.get("title", series_id),
                units=info.get("units", "Unknown"),
                frequency=info.get("frequency", "Unknown"),
                seasonal_adjustment=info.get("seasonal_adjustment", "Unknown"),
                observation_start=pd.to_datetime(info.get("observation_start")),
                observation_end=pd.to_datetime(info.get("observation_end")),
                popularity=info.get("popularity", 0)
            )
        except Exception:
            return None

    def search(self, query: str, limit: int = 10) -> List[SeriesInfo]:
        """Search FRED for series matching query.

        Args:
            query: Search query string
            limit: Maximum results to return

        Returns:
            List of matching SeriesInfo objects

        Example:
            >>> results = provider.search("unemployment rate")
            >>> for r in results[:3]:
            ...     print(f"{r.series_id}: {r.title}")
        """
        try:
            results = self._client.search(query)
            if results is None or len(results) == 0:
                return []

            series_list = []
            for _, row in results.head(limit).iterrows():
                series_list.append(SeriesInfo(
                    series_id=row.get("id", row.name) if hasattr(row, "name") else str(row.get("id", "")),
                    title=row.get("title", ""),
                    units=row.get("units", "Unknown"),
                    frequency=row.get("frequency", "Unknown"),
                    seasonal_adjustment=row.get("seasonal_adjustment", "Unknown"),
                    observation_start=pd.to_datetime(row.get("observation_start")),
                    observation_end=pd.to_datetime(row.get("observation_end")),
                    popularity=row.get("popularity", 0)
                ))
            return series_list

        except Exception:
            return []

    def validate_api_key(self) -> bool:
        """Check if the FRED API key is valid.

        Attempts to fetch a known series to verify the key works.

        Returns:
            True if API key is valid
        """
        try:
            # Try to get info for a common series
            self._client.get_series_info("GNPCA")
            return True
        except Exception:
            return False

    def get_releases(self, limit: int = 100) -> List[dict]:
        """Fetch FRED releases metadata.

        Args:
            limit: Maximum number of releases to fetch

        Returns:
            List of release dictionaries
        """
        try:
            # fredapi doesn't expose releases directly, use raw request
            import requests
            response = requests.get(
                f"{self.base_url}/releases",
                params={"api_key": self.api_key, "file_type": "json", "limit": limit},
                timeout=30
            )
            response.raise_for_status()
            return response.json().get("releases", [])
        except Exception:
            return []
