"""Type definitions for economic data integration.

Provides standardized data structures for economic time series data,
ensuring consistent interfaces across different data providers
(FRED, Fed, etc.).
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Dict, Any, List

import pandas as pd


@dataclass
class EconomicSeries:
    """Standardized economic time series data.

    Attributes:
        series_id: Unique identifier (e.g., "FEDFUNDS", "UNRATE")
        title: Human-readable series title
        data: Time series data as pandas Series with DatetimeIndex
        units: Units of measurement (e.g., "Percent", "Billions of Dollars")
        frequency: Data frequency (e.g., "Daily", "Monthly", "Quarterly")
        source: Data provider (e.g., "FRED", "Fed")
        last_updated: When the data was last updated at source
        metadata: Additional metadata from the provider

    Example:
        >>> series = EconomicSeries(
        ...     series_id="FEDFUNDS",
        ...     title="Federal Funds Effective Rate",
        ...     data=pd.Series([5.33, 5.33], index=pd.to_datetime(["2024-01-01", "2024-01-02"])),
        ...     units="Percent",
        ...     frequency="Daily",
        ...     source="FRED"
        ... )
    """
    series_id: str
    title: str
    data: pd.Series
    units: str = "Unknown"
    frequency: str = "Unknown"
    source: str = "Unknown"
    last_updated: Optional[datetime] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """Ensure data has DatetimeIndex."""
        if not isinstance(self.data.index, pd.DatetimeIndex):
            self.data.index = pd.to_datetime(self.data.index)

    def to_dataframe(self) -> pd.DataFrame:
        """Convert to DataFrame with series_id as column name."""
        return self.data.to_frame(name=self.series_id)

    @property
    def start_date(self) -> Optional[datetime]:
        """First observation date."""
        return self.data.index.min() if len(self.data) > 0 else None

    @property
    def end_date(self) -> Optional[datetime]:
        """Last observation date."""
        return self.data.index.max() if len(self.data) > 0 else None


@dataclass
class FetchResult:
    """Result from fetching economic data.

    Attributes:
        success: Whether the fetch succeeded
        series: The fetched series (None if failed)
        error: Error message (None if succeeded)
        source: Data source ("cache", "fred_api", etc.)
        cached: Whether data was served from cache
        fetch_time_ms: Time taken to fetch in milliseconds
        quality_report: Optional quality validation report
    """
    success: bool
    series: Optional[EconomicSeries] = None
    error: Optional[str] = None
    source: str = "unknown"
    cached: bool = False
    fetch_time_ms: float = 0.0
    quality_report: Optional[Any] = None  # QualityReport from quality.py


@dataclass
class SeriesInfo:
    """Metadata about an economic series without the actual data.

    Attributes:
        series_id: Unique identifier
        title: Human-readable title
        units: Units of measurement
        frequency: Data frequency
        seasonal_adjustment: Seasonal adjustment status
        observation_start: First available date
        observation_end: Last available date
        popularity: Popularity ranking (FRED-specific)
    """
    series_id: str
    title: str
    units: str = "Unknown"
    frequency: str = "Unknown"
    seasonal_adjustment: str = "Unknown"
    observation_start: Optional[datetime] = None
    observation_end: Optional[datetime] = None
    popularity: int = 0


# Common FRED series IDs for reference
FRED_SERIES = {
    # Fed policy rates
    "FEDFUNDS": "Federal Funds Effective Rate",
    "DFEDTAR": "Federal Funds Target Rate (single target era)",
    "DFEDTARL": "Federal Funds Target Rate Lower Bound",
    "DFEDTARU": "Federal Funds Target Rate Upper Bound",
    "DISCOUNT": "Primary Credit Rate",

    # Treasury yields
    "DGS10": "10-Year Treasury Constant Maturity Rate",
    "DGS2": "2-Year Treasury Constant Maturity Rate",
    "T10Y2Y": "10-Year Treasury Minus 2-Year Treasury",
    "DGS30": "30-Year Treasury Constant Maturity Rate",

    # Inflation indicators
    "CPIAUCSL": "Consumer Price Index for All Urban Consumers",
    "CPILFESL": "Core CPI (Excluding Food and Energy)",
    "PCEPI": "Personal Consumption Expenditures Price Index",
    "PCEPILFE": "Core PCE Price Index",

    # Employment data
    "UNRATE": "Unemployment Rate",
    "PAYEMS": "Total Nonfarm Payrolls",
    "ICSA": "Initial Claims",
    "JTSJOL": "Job Openings",
}
