from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import redis


class CandleCache:
    """Redis cache for latest and recent candles plus ingestion metadata."""

    def __init__(self, redis_url: str):
        self.redis = redis.Redis.from_url(redis_url, decode_responses=True)

    def cache_latest_candle(
        self,
        symbol: str,
        interval: str,
        candle: dict[str, Any],
        ttl_seconds: int,
    ) -> None:
        key = f"candles:latest:{symbol}:{interval}"
        self.redis.setex(key, ttl_seconds, json.dumps(self._serialize(candle)))

    def cache_recent_candles(
        self,
        symbol: str,
        interval: str,
        candles: list[dict[str, Any]],
        ttl_seconds: int,
    ) -> None:
        key = f"candles:recent:{symbol}:{interval}"
        payload = [self._serialize(c) for c in candles]
        self.redis.setex(key, ttl_seconds, json.dumps(payload))

    def cache_last_ingestion_time(
        self,
        symbol: str,
        interval: str,
        dt: datetime,
        ttl_seconds: int,
    ) -> None:
        key = f"ingestion:last:{symbol}:{interval}"
        self.redis.setex(key, ttl_seconds, dt.isoformat())

    def get_latest_candle(self, symbol: str, interval: str) -> dict[str, Any] | None:
        key = f"candles:latest:{symbol}:{interval}"
        raw = self.redis.get(key)
        if not raw:
            return None
        return json.loads(raw)

    def get_recent_candles(self, symbol: str, interval: str) -> list[dict[str, Any]] | None:
        key = f"candles:recent:{symbol}:{interval}"
        raw = self.redis.get(key)
        if not raw:
            return None
        return json.loads(raw)

    @staticmethod
    def _serialize(candle: dict[str, Any]) -> dict[str, Any]:
        out = dict(candle)
        dt = out.get("datetime")
        if isinstance(dt, datetime):
            out["datetime"] = dt.isoformat()
        return out
