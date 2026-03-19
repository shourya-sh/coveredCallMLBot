from __future__ import annotations

import threading
import time
from collections import deque
from datetime import datetime, timezone

from data_ingestion.postgres_repo import PostgresRepository


class QuotaExceededError(RuntimeError):
    """Raised when daily request quota has been exhausted."""


class TwelveDataRateLimiter:
    """
    Enforces both Twelve Data limits:
    - 8 requests in rolling 60 seconds
    - 800 requests per UTC day

    Uses an in-memory deque for minute-level precision and PostgreSQL
    persistence for daily usage so restarts do not reset counters.
    """

    def __init__(
        self,
        repository: PostgresRepository,
        per_minute_limit: int = 8,
        per_day_limit: int = 800,
        daily_safety_buffer: int = 8,
    ):
        self.repository = repository
        self.per_minute_limit = per_minute_limit
        self.per_day_limit = per_day_limit
        self.daily_safety_buffer = daily_safety_buffer
        self._timestamps = deque()
        self._lock = threading.Lock()

    def acquire(self) -> None:
        with self._lock:
            self._check_daily_quota()

            while True:
                now = time.monotonic()
                self._evict_old(now)
                if len(self._timestamps) < self.per_minute_limit:
                    self._timestamps.append(now)
                    break

                wait_for = 60.0 - (now - self._timestamps[0])
                if wait_for > 0:
                    time.sleep(wait_for)

            usage_date = datetime.now(tz=timezone.utc).date()
            updated_count = self.repository.increment_daily_usage(usage_date, count=1)
            if updated_count > self.per_day_limit:
                raise QuotaExceededError("Daily quota exceeded after request allocation")

    def _evict_old(self, now_monotonic: float) -> None:
        while self._timestamps and now_monotonic - self._timestamps[0] >= 60.0:
            self._timestamps.popleft()

    def _check_daily_quota(self) -> None:
        usage_date = datetime.now(tz=timezone.utc).date()
        current = self.repository.get_or_create_daily_usage(usage_date)
        if current >= (self.per_day_limit - self.daily_safety_buffer):
            raise QuotaExceededError(
                f"Daily quota guard reached ({current}/{self.per_day_limit}). Ingestion paused."
            )
