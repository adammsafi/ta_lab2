from abc import ABC, abstractmethod
from typing import Dict, List
import logging
import requests

# Set up a logger for the connectivity package
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class ExchangeInterface(ABC):
    """
    An abstract class representing the unified interface for all exchanges.
    """

    def __init__(self, api_key: str = None, api_secret: str = None, **kwargs):
        self.api_key = api_key
        self.api_secret = api_secret
        self.logger = logger
        self.session = requests.Session()  # Create a session object
        for key, value in kwargs.items():
            setattr(self, key, value)

    @abstractmethod
    def get_ticker(self, pair: str) -> Dict[str, float]:
        pass

    @abstractmethod
    def get_order_book(self, pair: str, depth: int) -> Dict[str, List[List[float]]]:
        pass

    @abstractmethod
    def get_historical_klines(
        self, pair: str, interval: str, start_time: int, end_time: int
    ) -> List[list]:
        pass

    @abstractmethod
    def get_account_balances(self) -> Dict[str, float]:
        pass

    @abstractmethod
    def get_open_orders(self, pair: str = None) -> List[dict]:
        pass

    @abstractmethod
    def place_limit_order(
        self, pair: str, side: str, price: float, amount: float
    ) -> Dict[str, str]:
        pass

    @abstractmethod
    def place_market_order(self, pair: str, side: str, amount: float) -> Dict[str, str]:
        pass

    @abstractmethod
    def cancel_order(self, order_id: str) -> Dict[str, str]:
        pass
