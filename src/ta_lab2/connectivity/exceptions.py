# src/ta_lab2/connectivity/exceptions.py


class APIError(Exception):
    """Base class for all API-related errors."""

    pass


class ConnectionError(APIError):
    """Raised when there's a problem connecting to the API."""

    pass


class AuthenticationError(APIError):
    """Raised for authentication failures."""

    pass


class RateLimitError(APIError):
    """Raised when the API rate limit is exceeded."""

    pass


class InvalidRequestError(APIError):
    """Raised for invalid requests (e.g., bad parameters)."""

    pass


class BadResponseError(APIError):
    """Raised for unexpected or malformed responses from the API."""

    pass
