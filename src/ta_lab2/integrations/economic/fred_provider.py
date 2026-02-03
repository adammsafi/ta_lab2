"""FRED data provider using fredapi.

Provides a working implementation of EconomicDataProvider that wraps
the fredapi library. Includes graceful degradation when fredapi is
not installed.

Install fredapi with: pip install ta_lab2[fred]
"""
import logging
import os
from datetime import datetime
from typing import Optional, List, Dict, Any

import pandas as pd

from ta_lab2.integrations.economic.base import EconomicDataProvider
from ta_lab2.integrations.economic.types import (
    EconomicSeries,
    FetchResult,
    SeriesInfo,
)
from ta_lab2.integrations.economic.rate_limiter import (
    get_fred_rate_limiter,
    RateLimiter,
)
from ta_lab2.integrations.economic.cache import get_economic_cache, EconomicDataCache
from ta_lab2.integrations.economic.circuit_breaker import (
    CircuitBreaker,
    CircuitOpenError,
)
from ta_lab2.integrations.economic.quality import QualityValidator, QualityReport

logger = logging.getLogger(__name__)

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
        """Initialize FRED provider with reliability features.

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

        # Reliability components
        self._rate_limiter: RateLimiter = get_fred_rate_limiter()
        self._cache: EconomicDataCache = get_economic_cache()
        self._circuit_breaker: CircuitBreaker = CircuitBreaker(
            failure_threshold=5, recovery_timeout=60.0, success_threshold=2
        )
        self._validator: QualityValidator = QualityValidator()

    def get_series(
        self,
        series_id: str,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        validate: bool = True,
        **kwargs,
    ) -> FetchResult:
        """Fetch series with rate limiting, caching, circuit breaker, and validation.

        Flow:
        1. Check cache first
        2. If cache miss, acquire rate limiter token
        3. Make API call through circuit breaker
        4. Validate data quality (if enabled)
        5. Cache successful result
        6. Return FetchResult

        Args:
            series_id: FRED series ID (e.g., "FEDFUNDS", "UNRATE")
            start_date: Optional start date filter
            end_date: Optional end date filter
            validate: Whether to run quality validation (default True)
            **kwargs: Additional options (frequency, aggregation_method, units)

        Returns:
            FetchResult with EconomicSeries on success, error message on failure

        Example:
            >>> result = provider.get_series("UNRATE", start_date=datetime(2020, 1, 1))
            >>> if result.success:
            ...     print(result.series.data.tail())
        """
        # Build cache key params
        cache_params = {}
        if start_date:
            cache_params["start_date"] = start_date.isoformat()
        if end_date:
            cache_params["end_date"] = end_date.isoformat()

        # 1. Check cache first
        cached = self._cache.get(series_id, **cache_params)
        if cached is not None:
            return FetchResult(
                success=True,
                series=cached,
                source="cache",
                cached=True,
            )

        # 2. Acquire rate limiter token (blocks if rate limited)
        if not self._rate_limiter.acquire(blocking=True, timeout=30.0):
            return FetchResult(
                success=False,
                error="Rate limit timeout - too many requests",
                source="fred_api",
            )

        # 3. Make API call through circuit breaker
        def _fetch_from_api() -> EconomicSeries:
            data = self._client.get_series(
                series_id,
                observation_start=start_date,
                observation_end=end_date,
                **kwargs,
            )
            info = self._client.get_series_info(series_id)
            return EconomicSeries(
                series_id=series_id,
                title=info.get("title", series_id),
                data=data,
                units=info.get("units", "Unknown"),
                frequency=info.get("frequency", "Unknown"),
                source="FRED",
                last_updated=pd.to_datetime(info.get("last_updated")),
                metadata=dict(info),
            )

        try:
            series = self._circuit_breaker.call(_fetch_from_api)
        except CircuitOpenError as e:
            return FetchResult(
                success=False,
                error=str(e),
                source="fred_api",
            )
        except Exception as e:
            return FetchResult(
                success=False,
                error=f"API error: {e}",
                source="fred_api",
            )

        # 4. Validate data quality (if enabled)
        quality_report: Optional[QualityReport] = None
        if validate:
            quality_report = self._validator.validate(series)
            if not quality_report.is_valid:
                # Log warnings but don't fail - data may still be usable
                for issue in quality_report.issues:
                    if issue.severity == "error":
                        logger.warning(f"Quality issue in {series_id}: {issue.message}")

        # 5. Cache successful result
        self._cache.set(series_id, series, **cache_params)

        # 6. Return result
        return FetchResult(
            success=True,
            series=series,
            source="fred_api",
            cached=False,
            quality_report=quality_report,
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
                popularity=info.get("popularity", 0),
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
                series_list.append(
                    SeriesInfo(
                        series_id=row.get("id", row.name)
                        if hasattr(row, "name")
                        else str(row.get("id", "")),
                        title=row.get("title", ""),
                        units=row.get("units", "Unknown"),
                        frequency=row.get("frequency", "Unknown"),
                        seasonal_adjustment=row.get("seasonal_adjustment", "Unknown"),
                        observation_start=pd.to_datetime(row.get("observation_start")),
                        observation_end=pd.to_datetime(row.get("observation_end")),
                        popularity=row.get("popularity", 0),
                    )
                )
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
                timeout=30,
            )
            response.raise_for_status()
            return response.json().get("releases", [])
        except Exception:
            return []

    def get_reliability_stats(self) -> Dict[str, Any]:
        """Get statistics from all reliability components.

        Returns:
            Dict with rate_limiter, cache, and circuit_breaker stats
        """
        return {
            "rate_limiter": {
                "available_tokens": self._rate_limiter.available_tokens,
                "max_tokens": self._rate_limiter.max_tokens,
            },
            "cache": self._cache.stats(),
            "circuit_breaker": {
                "state": self._circuit_breaker.state.value,
                "failure_count": self._circuit_breaker.stats().failure_count,
            },
        }
