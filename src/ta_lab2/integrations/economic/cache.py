"""TTL caching for economic data.

Provides in-memory caching with time-to-live expiration to avoid
repeated API calls for the same data.
"""
import hashlib
import json
import threading
import time
from dataclasses import dataclass
from typing import Optional, Any, Dict


@dataclass
class CacheEntry:
    """Cache entry with value and expiration time."""

    value: Any
    expires_at: float
    created_at: float

    @property
    def is_expired(self) -> bool:
        """Check if entry has expired."""
        return time.time() > self.expires_at


class EconomicDataCache:
    """In-memory TTL cache for economic data.

    Provides thread-safe caching with configurable TTL (time-to-live).
    Cache keys are generated from series ID and parameters.

    Attributes:
        default_ttl: Default time-to-live in seconds
        max_size: Maximum cache entries (LRU eviction)

    Example:
        >>> cache = EconomicDataCache(default_ttl=3600)  # 1 hour TTL
        >>> cache.set("FEDFUNDS", data)
        >>> result = cache.get("FEDFUNDS")
        >>> if result is not None:
        ...     print("Cache hit!")
    """

    def __init__(
        self,
        default_ttl: float = 3600.0,
        max_size: int = 1000,
    ):
        """Initialize cache.

        Args:
            default_ttl: Default TTL in seconds (1 hour default)
            max_size: Maximum entries before LRU eviction
        """
        self.default_ttl = default_ttl
        self.max_size = max_size
        self._cache: Dict[str, CacheEntry] = {}
        self._access_order: list = []  # For LRU tracking
        self._lock = threading.Lock()

    @staticmethod
    def _make_key(series_id: str, **params) -> str:
        """Generate cache key from series ID and parameters."""
        key_data = {"series_id": series_id, **params}
        key_json = json.dumps(key_data, sort_keys=True, default=str)
        return hashlib.md5(key_json.encode()).hexdigest()

    def get(self, series_id: str, **params) -> Optional[Any]:
        """Get value from cache.

        Args:
            series_id: Series identifier
            **params: Additional parameters (start_date, end_date, etc.)

        Returns:
            Cached value if present and not expired, None otherwise
        """
        key = self._make_key(series_id, **params)

        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                return None

            if entry.is_expired:
                del self._cache[key]
                if key in self._access_order:
                    self._access_order.remove(key)
                return None

            # Update LRU order
            if key in self._access_order:
                self._access_order.remove(key)
            self._access_order.append(key)

            return entry.value

    def set(
        self, series_id: str, value: Any, ttl: Optional[float] = None, **params
    ) -> None:
        """Set value in cache.

        Args:
            series_id: Series identifier
            value: Value to cache
            ttl: Optional TTL override in seconds
            **params: Additional parameters for cache key
        """
        key = self._make_key(series_id, **params)
        ttl = ttl if ttl is not None else self.default_ttl
        now = time.time()

        entry = CacheEntry(value=value, expires_at=now + ttl, created_at=now)

        with self._lock:
            # Evict if at capacity
            while len(self._cache) >= self.max_size and self._access_order:
                oldest_key = self._access_order.pop(0)
                self._cache.pop(oldest_key, None)

            self._cache[key] = entry

            # Update LRU order
            if key in self._access_order:
                self._access_order.remove(key)
            self._access_order.append(key)

    def invalidate(self, series_id: str, **params) -> bool:
        """Invalidate a specific cache entry.

        Args:
            series_id: Series identifier
            **params: Additional parameters

        Returns:
            True if entry was removed, False if not found
        """
        key = self._make_key(series_id, **params)

        with self._lock:
            if key in self._cache:
                del self._cache[key]
                if key in self._access_order:
                    self._access_order.remove(key)
                return True
            return False

    def clear(self) -> int:
        """Clear all cache entries.

        Returns:
            Number of entries cleared
        """
        with self._lock:
            count = len(self._cache)
            self._cache.clear()
            self._access_order.clear()
            return count

    def cleanup_expired(self) -> int:
        """Remove all expired entries.

        Returns:
            Number of entries removed
        """
        with self._lock:
            expired_keys = [k for k, v in self._cache.items() if v.is_expired]
            for key in expired_keys:
                del self._cache[key]
                if key in self._access_order:
                    self._access_order.remove(key)
            return len(expired_keys)

    @property
    def size(self) -> int:
        """Current number of cached entries."""
        return len(self._cache)

    def stats(self) -> Dict[str, Any]:
        """Get cache statistics.

        Returns:
            Dict with size, max_size, default_ttl
        """
        return {
            "size": self.size,
            "max_size": self.max_size,
            "default_ttl": self.default_ttl,
        }


# Global cache instance
_economic_cache: Optional[EconomicDataCache] = None


def get_economic_cache() -> EconomicDataCache:
    """Get or create the global economic data cache.

    Returns:
        EconomicDataCache instance with 1-hour default TTL
    """
    global _economic_cache
    if _economic_cache is None:
        _economic_cache = EconomicDataCache(default_ttl=3600.0, max_size=1000)
    return _economic_cache
