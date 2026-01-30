"""
Validation test fixtures.

Provides fixtures for gap detection and alignment validation tests.
"""

import pytest
import pandas as pd
from datetime import datetime, timedelta


@pytest.fixture
def test_assets():
    """
    Sample asset IDs for validation tests.

    Returns commonly used asset IDs (BTC=1, ETH=52) for testing.
    """
    return [1, 52]  # BTC, ETH commonly used


@pytest.fixture
def expected_dates():
    """
    Generate expected date range for gap testing.

    Returns a 30-day date range ending today for testing gap detection.
    """
    end = datetime.now().date()
    start = end - timedelta(days=30)
    return pd.date_range(start, end, freq='D')


@pytest.fixture
def mock_dim_sessions():
    """
    Mock trading session data for testing session-aware gap detection.

    Returns session configurations for crypto (24/7) and equity (trading days).
    """
    return {
        'crypto': {
            'session': 'CRYPTO',
            'daily': True,
        },
        'equity': {
            'session': 'NYSE',
            'daily': False,
            'trading_days': [0, 1, 2, 3, 4],  # Monday-Friday
        },
    }
