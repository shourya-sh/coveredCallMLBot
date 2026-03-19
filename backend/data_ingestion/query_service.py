from __future__ import annotations

from datetime import datetime

from data_ingestion.candle_cache import CandleCache
from data_ingestion.postgres_repo import PostgresRepository


class CandleQueryService:
    """Efficient historical/live retrieval with Redis read-through caching."""

    def __init__(self, repository: PostgresRepository, cache: CandleCache):
        self.repository = repository
        self.cache = cache

    def latest_candle(self, ticker: str, interval: str) -> dict | None:
        ticker = ticker.upper()
        cached = self.cache.get_latest_candle(ticker, interval)
        if cached is not None:
            return cached

        symbol = self.repository.get_symbol_by_ticker(ticker)
        if not symbol:
            return None

        candle = self.repository.get_latest_candle(symbol["id"], interval)
        if candle:
            ttl = self._ttl_for_priority(symbol.get("priority", 5))
            self.cache.cache_latest_candle(ticker, interval, candle, ttl_seconds=ttl)
        return candle

    def recent_candles(self, ticker: str, interval: str, limit: int = 50) -> list[dict]:
        ticker = ticker.upper()
        cached = self.cache.get_recent_candles(ticker, interval)
        if cached is not None and len(cached) >= min(limit, 50):
            return cached[-limit:]

        symbol = self.repository.get_symbol_by_ticker(ticker)
        if not symbol:
            return []

        candles = self.repository.get_recent_candles(symbol["id"], interval, limit=max(limit, 50))
        if candles:
            ttl = self._ttl_for_priority(symbol.get("priority", 5))
            self.cache.cache_recent_candles(ticker, interval, candles[-50:], ttl_seconds=ttl)
        return candles[-limit:]

    def historical_candles(
        self,
        ticker: str,
        interval: str,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 5000,
    ) -> list[dict]:
        ticker = ticker.upper()
        symbol = self.repository.get_symbol_by_ticker(ticker)
        if not symbol:
            return []

        return self.repository.get_candles_in_range(
            symbol_id=symbol["id"],
            interval=interval,
            start=start,
            end=end,
            limit=limit,
        )

    @staticmethod
    def _ttl_for_priority(priority: int) -> int:
        if priority <= 3:
            return 60 * 2
        if priority <= 5:
            return 60 * 5
        return 60 * 15
