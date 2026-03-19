from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone

from data_ingestion.ingestion_service import IngestionResult, IngestionService
from data_ingestion.rate_limiter import QuotaExceededError

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SchedulerConfig:
    intervals: tuple[str, ...] = ("5min", "1day")
    max_symbols_per_cycle: int = 5
    cycle_seconds: int = 60
    high_priority_threshold: int = 3
    interval_cadence_seconds: dict[str, int] | None = None


class RotatingIngestionScheduler:
    """
    Fair rotating scheduler with priority-aware batching.

    High-priority symbols are serviced every cycle.
    Lower-priority symbols are always allocated slots so they are never starved.
    """

    def __init__(
        self,
        service: IngestionService,
        symbols: list[dict],
        config: SchedulerConfig,
    ):
        self.service = service
        self.config = config
        self.high_queue = deque(
            [s for s in symbols if int(s.get("priority", 5)) <= config.high_priority_threshold]
        )
        self.low_queue = deque(
            [s for s in symbols if int(s.get("priority", 5)) > config.high_priority_threshold]
        )

        # If all symbols are high or low, still run from available queue.
        if not self.high_queue and self.low_queue:
            self.high_queue = deque(self.low_queue)
        if not self.low_queue and self.high_queue:
            self.low_queue = deque(self.high_queue)

        self.interval_cadence_seconds = config.interval_cadence_seconds or {
            # Fetch 5-minute candles every 10 minutes; incremental requests cover missing bars.
            "5min": 600,
            # Daily bars need very infrequent checks.
            "1day": 21600,
            "1min": 600,
            "1h": 3600,
        }
        self._next_run: dict[tuple[str, str], float] = {}

    def run_forever(self) -> None:
        while True:
            cycle_start = time.monotonic()
            utc_now = datetime.now(tz=timezone.utc).isoformat()
            logger.info("Starting ingestion cycle at %s", utc_now)

            batch = self._next_symbol_batch(self.config.max_symbols_per_cycle)
            for symbol in batch:
                for interval in self.config.intervals:
                    if not self._is_due(symbol["ticker"], interval, cycle_start):
                        continue
                    try:
                        result = self.service.ingest_symbol_interval(symbol, interval, full_backfill=False)
                        self._log_result(result)
                        self._schedule_next(symbol["ticker"], interval, cycle_start)
                    except QuotaExceededError as exc:
                        logger.warning("Quota guard tripped: %s", exc)
                        return

            elapsed = time.monotonic() - cycle_start
            sleep_for = max(0.0, self.config.cycle_seconds - elapsed)
            if sleep_for > 0:
                time.sleep(sleep_for)

    def run_once(self, full_backfill: bool) -> list[IngestionResult]:
        results: list[IngestionResult] = []
        combined = list(self.high_queue) + list(self.low_queue)
        seen = set()
        unique_symbols = []
        for symbol in combined:
            ticker = symbol["ticker"]
            if ticker not in seen:
                unique_symbols.append(symbol)
                seen.add(ticker)

        for symbol in unique_symbols:
            for interval in self.config.intervals:
                try:
                    result = self.service.ingest_symbol_interval(
                        symbol,
                        interval,
                        full_backfill=full_backfill,
                    )
                    results.append(result)
                    self._log_result(result)
                except QuotaExceededError as exc:
                    logger.warning("Quota guard tripped: %s", exc)
                    return results
        return results

    def _next_symbol_batch(self, max_symbols: int) -> list[dict]:
        if max_symbols <= 0:
            return []

        batch: list[dict] = []

        high_slots = max_symbols // 2 + max_symbols % 2
        low_slots = max_symbols - high_slots

        batch.extend(self._pull_from_queue(self.high_queue, high_slots))
        batch.extend(self._pull_from_queue(self.low_queue, low_slots))

        if len(batch) < max_symbols:
            batch.extend(self._pull_from_queue(self.high_queue, max_symbols - len(batch)))

        return batch[:max_symbols]

    def _is_due(self, ticker: str, interval: str, now_monotonic: float) -> bool:
        next_due = self._next_run.get((ticker, interval))
        return next_due is None or now_monotonic >= next_due

    def _schedule_next(self, ticker: str, interval: str, now_monotonic: float) -> None:
        cadence = self.interval_cadence_seconds.get(interval, self.config.cycle_seconds)
        self._next_run[(ticker, interval)] = now_monotonic + cadence

    @staticmethod
    def _pull_from_queue(queue: deque, count: int) -> list[dict]:
        pulled = []
        for _ in range(count):
            if not queue:
                break
            item = queue.popleft()
            queue.append(item)
            pulled.append(item)
        return pulled

    @staticmethod
    def _log_result(result: IngestionResult) -> None:
        if result.status == "success":
            logger.info(
                "Ingested %s %s: fetched=%s upserted=%s",
                result.symbol,
                result.interval,
                result.fetched_rows,
                result.inserted_rows,
            )
        elif result.status == "cooldown":
            logger.info("Cooldown %s %s: %s", result.symbol, result.interval, result.error_message)
        else:
            logger.warning("Failed %s %s: %s", result.symbol, result.interval, result.error_message)
