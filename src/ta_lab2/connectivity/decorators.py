# src/ta_lab2/connectivity/decorators.py

from functools import wraps
import requests
from .exceptions import (
    APIError,
    ConnectionError,
    AuthenticationError,
    RateLimitError,
    InvalidRequestError,
    BadResponseError,
)


def handle_api_errors(func):
    """
    A decorator to handle common API request errors and wrap them in custom exceptions.
    """

    @wraps(func)
    def wrapper(self, *args, **kwargs):
        try:
            return func(self, *args, **kwargs)
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 401 or e.response.status_code == 403:
                raise AuthenticationError(f"Authentication failed: {e}") from e
            elif e.response.status_code == 429:
                raise RateLimitError(f"Rate limit exceeded: {e}") from e
            elif 400 <= e.response.status_code < 500:
                raise InvalidRequestError(f"Invalid request: {e}") from e
            else:
                raise APIError(f"HTTP error occurred: {e}") from e
        except requests.exceptions.RequestException as e:
            raise ConnectionError(f"Connection error: {e}") from e
        except (KeyError, IndexError, TypeError, ValueError) as e:
            # Catches issues with parsing the response (e.g., missing keys)
            raise BadResponseError(f"Failed to parse response: {e}") from e

    return wrapper
