from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx


@dataclass(frozen=True)
class TDIngestionConfig:
    api_key: str
    base_url: str = "https://api.twelvedata.com"
    timeout_seconds: int = 20
    max_retries: int = 4
    max_outputsize: int = 5000


class TwelveDataIngestionClient:
    """Low-level Twelve Data time_series client tuned for bulk candle ingestion."""

    def __init__(self, config: TDIngestionConfig):
        self.config = config
        self.client = httpx.Client(timeout=config.timeout_seconds)

    def close(self) -> None:
        self.client.close()

    def __enter__(self) -> "TwelveDataIngestionClient":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

    def fetch_max_candles(
        self,
        symbol: str,
        interval: str,
        start_date: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """
        Always requests maximum payload size to minimize API calls.

        For incremental updates, pass start_date to avoid re-fetching full history.
        """
        params = {
            "symbol": symbol,
            "interval": interval,
            "outputsize": self.config.max_outputsize,
            "apikey": self.config.api_key,
            "timezone": "UTC",
            "order": "ASC",
        }
        if start_date is not None:
            dt = start_date.astimezone(timezone.utc).replace(microsecond=0)
            params["start_date"] = dt.strftime("%Y-%m-%d %H:%M:%S")

        url = f"{self.config.base_url}/time_series"
        data = self._request_json(url, params)

        values = data.get("values", [])
        normalized = []
        for item in values:
            ts = self._parse_datetime(item["datetime"])
            normalized.append(
                {
                    "datetime": ts,
                    "open": float(item["open"]),
                    "high": float(item["high"]),
                    "low": float(item["low"]),
                    "close": float(item["close"]),
                    "volume": int(float(item["volume"])) if item.get("volume") not in (None, "") else None,
                }
            )

        return normalized

    def _request_json(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        last_error: Exception | None = None

        for attempt in range(self.config.max_retries):
            try:
                response = self.client.get(url, params=params)
                response.raise_for_status()
                payload = response.json()
                if payload.get("status") == "error":
                    message = payload.get("message", "Unknown API error")
                    raise RuntimeError(f"Twelve Data API error: {message}")
                return payload
            except (httpx.HTTPError, RuntimeError) as exc:
                last_error = exc
                if attempt == self.config.max_retries - 1:
                    break

                # 1s, 2s, 4s, 8s backoff pattern.
                delay = 2 ** attempt
                import time

                time.sleep(delay)

        raise RuntimeError(f"Failed Twelve Data request after retries: {last_error}")

    @staticmethod
    def _parse_datetime(value: str) -> datetime:
        patterns = ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d"]
        for pattern in patterns:
            try:
                dt = datetime.strptime(value, pattern)
                return dt.replace(tzinfo=timezone.utc)
            except ValueError:
                continue
        raise ValueError(f"Unsupported Twelve Data datetime format: {value}")
