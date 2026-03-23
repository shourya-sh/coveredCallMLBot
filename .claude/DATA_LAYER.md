# Twelve Data Infrastructure Layer

This backend data layer is designed for long-running, quota-aware candle ingestion.

## 1) PostgreSQL Schema

Schema file:
- `sql/postgres_schema.sql`

Core tables:
- `symbols`
- `candles`
- `indicators`
- `ingestion_logs`

Support tables used by ingestion controls:
- `api_usage_daily` (persists 800/day quota accounting)
- `ingestion_state` (cooldown after repeated failures)

## 2) Ingestion Pipeline

Entrypoint:
- `run_ingestion.py`

Core modules:
- `data_ingestion/twelve_data_ingestion_client.py`
- `data_ingestion/postgres_repo.py`
- `data_ingestion/ingestion_service.py`
- `data_ingestion/rate_limiter.py`
- `data_ingestion/scheduler.py`

First run:
- Run with `--once --backfill` to fetch full history using max output size.

Subsequent runs:
- Start scheduler normally.
- Incremental fetch uses latest candle timestamp from DB and passes `start_date` so only missing candles are requested.

## 3) Strict Rate Limiting

Implemented in `data_ingestion/rate_limiter.py`.

Controls:
- Rolling window: max 8 requests per 60 seconds.
- Daily quota: max 800 requests per UTC day.
- Daily counter persisted in PostgreSQL (`api_usage_daily`) so restarts do not reset usage.

## 4) Scheduling Strategy

Implemented in `data_ingestion/scheduler.py`.

Behavior:
- Priority-aware rotation (high and low priority queues).
- Max symbols per cycle is configurable (default 5).
- Per-interval cadence reduces waste:
  - `5min` default cadence: every 600 seconds
  - `1day` default cadence: every 21600 seconds
- No starvation: low-priority queue always receives slots.

## 5) Redis Caching

Implemented in `data_ingestion/candle_cache.py` and used by:
- `data_ingestion/ingestion_service.py`
- `data_ingestion/query_service.py`

Cached keys:
- `candles:latest:{symbol}:{interval}`
- `candles:recent:{symbol}:{interval}` (last ~50)
- `ingestion:last:{symbol}:{interval}`

TTL strategy:
- Active symbols (priority <= 3): 2 minutes
- Medium: 5 minutes
- Low activity: 15 minutes

## 6) Max-Candle API Usage

All ingestion calls request maximum candles:

```python
params = {
    "symbol": symbol,
    "interval": interval,
    "outputsize": 5000,
    "apikey": api_key,
    "timezone": "UTC",
    "order": "ASC",
}
```

For incremental runs:

```python
params["start_date"] = latest_candle_plus_1s
```

This keeps requests large and infrequent, minimizes API usage, and prevents fragmented local history.

## 7) Tracked Symbols

Seeded by default in `run_ingestion.py`:
- SPY, QQQ, IWM, AAPL, NVDA, TSLA, AMZN, MSFT, META, SPX

## 8) CLI Usage

Install backend dependencies first:

```bash
pip install -r backend/requirements.txt
```

Required environment variables (`backend/.env`):

```bash
POSTGRES_DSN=postgresql://user:password@localhost:5432/dashy
REDIS_URL=redis://localhost:6379/0
TWELVE_DATA_API_KEY=your_api_key
```

One-time full backfill:

```bash
python backend/run_ingestion.py --once --backfill --intervals 5min,1day
```

Single incremental pass (manual trigger):

```bash
python backend/run_ingestion.py --once --intervals 5min,1day
```

Continuous scheduler:

```bash
python backend/run_ingestion.py --intervals 5min,1day --batch-size 5 --cycle-seconds 60
```

Optional cadence override:

```bash
INGESTION_INTERVAL_CADENCE=5min=600,1day=21600,1h=3600,1min=600
```
