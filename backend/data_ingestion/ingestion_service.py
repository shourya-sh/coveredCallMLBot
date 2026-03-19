from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from data_ingestion.candle_cache import CandleCache
from data_ingestion.postgres_repo import CandleRow, PostgresRepository
from data_ingestion.rate_limiter import QuotaExceededError, TwelveDataRateLimiter
from data_ingestion.twelve_data_ingestion_client import TwelveDataIngestionClient

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class IngestionResult:
    symbol: str
    interval: str
    inserted_rows: int
    fetched_rows: int
    status: str
    error_message: str | None = None


class IngestionService:
    """Coordinates incremental candle ingestion with strict quota and retries."""

    def __init__(
        self,
        repository: PostgresRepository,
        td_client: TwelveDataIngestionClient,
        limiter: TwelveDataRateLimiter,
        cache: CandleCache,
    ):
        self.repository = repository
        self.td_client = td_client
        self.limiter = limiter
        self.cache = cache

    def ingest_symbol_interval(
        self,
        symbol_row: dict,
        interval: str,
        full_backfill: bool = False,
    ) -> IngestionResult:
        symbol_id = symbol_row["id"]
        ticker = symbol_row["ticker"]
        now = datetime.now(tz=timezone.utc)

        cooldown_until = self.repository.get_cooldown_until(symbol_id, interval)
        if cooldown_until and cooldown_until > now:
            message = f"Skipping {ticker} {interval}: cooldown until {cooldown_until.isoformat()}"
            logger.info(message)
            return IngestionResult(
                symbol=ticker,
                interval=interval,
                inserted_rows=0,
                fetched_rows=0,
                status="cooldown",
                error_message=message,
            )

        latest = self.repository.latest_candle_time(symbol_id, interval)
        start_date = None
        if latest and not full_backfill:
            # Advance one second to avoid re-fetching the last saved candle.
            start_date = latest.astimezone(timezone.utc) + timedelta(seconds=1)

        try:
            self.limiter.acquire()
            candles = self.td_client.fetch_max_candles(
                symbol=ticker,
                interval=interval,
                start_date=start_date,
            )

            new_rows = []
            for item in candles:
                if latest and item["datetime"] <= latest and not full_backfill:
                    continue
                new_rows.append(
                    CandleRow(
                        symbol_id=symbol_id,
                        datetime=item["datetime"],
                        open=item["open"],
                        high=item["high"],
                        low=item["low"],
                        close=item["close"],
                        volume=item["volume"],
                        interval=interval,
                    )
                )

            inserted = self.repository.upsert_candles(new_rows)
            latest_after = new_rows[-1].datetime if new_rows else latest

            self.repository.record_ingestion_log(
                symbol_id=symbol_id,
                interval=interval,
                status="success",
                last_candle_time=latest_after,
                error_message=None,
            )
            self.repository.update_ingestion_state_success(symbol_id, interval, now)

            if latest_after:
                ttl = self._ttl_for_priority(symbol_row.get("priority", 5))
                latest_candle = self.repository.get_latest_candle(symbol_id, interval)
                if latest_candle:
                    self.cache.cache_latest_candle(ticker, interval, latest_candle, ttl_seconds=ttl)
                recent = self.repository.get_recent_candles(symbol_id, interval, limit=50)
                if recent:
                    self.cache.cache_recent_candles(ticker, interval, recent, ttl_seconds=ttl)
                self.cache.cache_last_ingestion_time(ticker, interval, latest_after, ttl_seconds=ttl)

            return IngestionResult(
                symbol=ticker,
                interval=interval,
                inserted_rows=inserted,
                fetched_rows=len(candles),
                status="success",
            )

        except QuotaExceededError:
            raise
        except Exception as exc:
            failures = self.repository.update_ingestion_state_failure(
                symbol_id=symbol_id,
                interval=interval,
                now=now,
                cooldown_until=now,
            )
            backoff_minutes = self._failure_backoff_minutes(failures)
            cooldown_until = now + timedelta(minutes=backoff_minutes)
            self.repository.set_cooldown_until(
                symbol_id=symbol_id,
                interval=interval,
                now=now,
                cooldown_until=cooldown_until,
            )
            self.repository.record_ingestion_log(
                symbol_id=symbol_id,
                interval=interval,
                status="failed",
                last_candle_time=latest,
                error_message=str(exc),
            )
            return IngestionResult(
                symbol=ticker,
                interval=interval,
                inserted_rows=0,
                fetched_rows=0,
                status="failed",
                error_message=str(exc),
            )

    def _failure_backoff_minutes(self, failures: int) -> int:
        return min(2 ** max(0, failures - 1), 60)

    @staticmethod
    def _ttl_for_priority(priority: int) -> int:
        # Lower priority number means more active symbol.
        if priority <= 3:
            return 60 * 2
        if priority <= 5:
            return 60 * 5
        return 60 * 15
