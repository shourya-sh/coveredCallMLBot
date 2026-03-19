"""
In-memory cache with TTL for stock/options data.
Fetches from Twelve Data at most once per CACHE_TTL_SECONDS.
"""

import time
import threading
from typing import Any, Dict, Optional


CACHE_TTL_SECONDS = 15 * 60  # 15 minutes


class DataCache:
    """Thread-safe TTL cache for stock data."""

    def __init__(self, ttl: int = CACHE_TTL_SECONDS):
        self.ttl = ttl
        self._store: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            if time.time() - entry["ts"] > self.ttl:
                del self._store[key]
                return None
            return entry["value"]

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            self._store[key] = {"value": value, "ts": time.time()}

    def last_updated(self, key: str) -> Optional[float]:
        with self._lock:
            entry = self._store.get(key)
            return entry["ts"] if entry else None

    def clear(self) -> None:
        with self._lock:
            self._store.clear()


# Singleton
cache = DataCache()
