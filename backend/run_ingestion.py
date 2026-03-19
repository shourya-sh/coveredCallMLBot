from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from psycopg_pool import ConnectionPool

from data_ingestion.candle_cache import CandleCache
from data_ingestion.ingestion_service import IngestionService
from data_ingestion.postgres_pool import apply_schema, create_pool, get_connection
from data_ingestion.postgres_repo import PostgresRepository
from data_ingestion.rate_limiter import TwelveDataRateLimiter
from data_ingestion.scheduler import RotatingIngestionScheduler, SchedulerConfig
from data_ingestion.twelve_data_ingestion_client import TDIngestionConfig, TwelveDataIngestionClient

# Ensure env is loaded from backend/.env even when invoked from workspace root.
load_dotenv(Path(__file__).resolve().parent / ".env")

logging.basicConfig(
    level=os.getenv("INGESTION_LOG_LEVEL", "INFO"),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

DEFAULT_TRACKED_SYMBOLS = [
    {"ticker": "SPY", "name": "SPDR S&P 500 ETF Trust", "exchange": "NYSE ARCA", "asset_type": "ETF", "priority": 1},
    {"ticker": "QQQ", "name": "Invesco QQQ Trust", "exchange": "NASDAQ", "asset_type": "ETF", "priority": 1},
    {"ticker": "IWM", "name": "iShares Russell 2000 ETF", "exchange": "NYSE ARCA", "asset_type": "ETF", "priority": 2},
    {"ticker": "AAPL", "name": "Apple Inc.", "exchange": "NASDAQ", "asset_type": "Common Stock", "priority": 2},
    {"ticker": "NVDA", "name": "NVIDIA Corporation", "exchange": "NASDAQ", "asset_type": "Common Stock", "priority": 2},
    {"ticker": "TSLA", "name": "Tesla, Inc.", "exchange": "NASDAQ", "asset_type": "Common Stock", "priority": 2},
    {"ticker": "AMZN", "name": "Amazon.com, Inc.", "exchange": "NASDAQ", "asset_type": "Common Stock", "priority": 3},
    {"ticker": "MSFT", "name": "Microsoft Corporation", "exchange": "NASDAQ", "asset_type": "Common Stock", "priority": 3},
    {"ticker": "META", "name": "Meta Platforms, Inc.", "exchange": "NASDAQ", "asset_type": "Common Stock", "priority": 3},
    {"ticker": "SPX", "name": "S&P 500 Index", "exchange": "INDEX", "asset_type": "Index", "priority": 1},
]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Quota-aware Twelve Data ingestion service")
    parser.add_argument("--once", action="store_true", help="Run one ingestion pass then exit")
    parser.add_argument("--backfill", action="store_true", help="Force full-history backfill (max outputsize)")
    parser.add_argument(
        "--intervals",
        default=os.getenv("INGESTION_INTERVALS", "5min,1day"),
        help="Comma-separated intervals, e.g. 1min,5min,1h,1day",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=int(os.getenv("INGESTION_BATCH_SIZE", "5")),
        help="Symbols per scheduler cycle",
    )
    parser.add_argument(
        "--cycle-seconds",
        type=int,
        default=int(os.getenv("INGESTION_CYCLE_SECONDS", "60")),
        help="Scheduler cycle duration",
    )
    return parser


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _init_symbols(repo: PostgresRepository) -> None:
    rows = []
    for item in DEFAULT_TRACKED_SYMBOLS:
        rows.append(
            {
                "ticker": item["ticker"],
                "name": item["name"],
                "exchange": item["exchange"],
                "asset_type": item["asset_type"],
                "priority": item["priority"],
                "is_active": True,
            }
        )
    repo.ensure_symbols(rows)


def _parse_interval_cadence(raw: str) -> dict[str, int]:
    # Format: "5min=600,1day=21600,1h=3600"
    parsed: dict[str, int] = {}
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        if "=" not in item:
            continue
        interval, seconds = item.split("=", 1)
        interval = interval.strip()
        seconds = seconds.strip()
        if not interval or not seconds.isdigit():
            continue
        parsed[interval] = int(seconds)
    return parsed


def _build_scheduler(pool: ConnectionPool, intervals: tuple[str, ...], batch_size: int, cycle_seconds: int):
    with get_connection(pool) as conn:
        repo = PostgresRepository(conn)
        _init_symbols(repo)
        symbols = repo.get_active_symbols()

        redis_url = _required_env("REDIS_URL")
        td_key = _required_env("TWELVE_DATA_API_KEY")

        cache = CandleCache(redis_url=redis_url)
        limiter = TwelveDataRateLimiter(repository=repo)
        td_client = TwelveDataIngestionClient(TDIngestionConfig(api_key=td_key))
        service = IngestionService(repo, td_client, limiter, cache)

        config = SchedulerConfig(
            intervals=intervals,
            max_symbols_per_cycle=batch_size,
            cycle_seconds=cycle_seconds,
            high_priority_threshold=int(os.getenv("INGESTION_HIGH_PRIORITY_THRESHOLD", "3")),
            interval_cadence_seconds=_parse_interval_cadence(
                os.getenv("INGESTION_INTERVAL_CADENCE", "5min=600,1day=21600,1h=3600,1min=600")
            ),
        )
        return RotatingIngestionScheduler(service=service, symbols=symbols, config=config), td_client


def main() -> None:
    args = build_parser().parse_args()
    intervals = tuple(i.strip() for i in args.intervals.split(",") if i.strip())

    postgres_dsn = _required_env("POSTGRES_DSN")
    schema_path = Path(__file__).resolve().parent / "sql" / "postgres_schema.sql"

    pool = create_pool(postgres_dsn)
    with get_connection(pool) as conn:
        apply_schema(conn, schema_path)

    scheduler = None
    td_client = None
    try:
        scheduler, td_client = _build_scheduler(pool, intervals, args.batch_size, args.cycle_seconds)
        if args.once:
            logger.info("Running single pass ingestion: backfill=%s intervals=%s", args.backfill, intervals)
            results = scheduler.run_once(full_backfill=args.backfill)
            success = len([r for r in results if r.status == "success"])
            failed = len([r for r in results if r.status == "failed"])
            logger.info("Single pass complete: success=%s failed=%s total=%s", success, failed, len(results))
        else:
            logger.info(
                "Starting continuous scheduler: batch=%s cycle=%ss intervals=%s",
                args.batch_size,
                args.cycle_seconds,
                intervals,
            )
            scheduler.run_forever()
    finally:
        if td_client is not None:
            td_client.close()
        pool.close()


if __name__ == "__main__":
    main()
