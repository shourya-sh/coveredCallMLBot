from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Iterable, Sequence

from psycopg import Connection
from psycopg.rows import dict_row


@dataclass(frozen=True)
class CandleRow:
    symbol_id: int
    datetime: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int | None
    interval: str


class PostgresRepository:
    """Repository wrapping all persistence operations for ingestion and retrieval."""

    def __init__(self, connection: Connection):
        self.connection = connection

    def ensure_symbols(self, symbols: Sequence[dict]) -> None:
        if not symbols:
            return

        sql = """
        INSERT INTO symbols (ticker, name, exchange, asset_type, priority, is_active)
        VALUES (%(ticker)s, %(name)s, %(exchange)s, %(asset_type)s, %(priority)s, %(is_active)s)
        ON CONFLICT (ticker)
        DO UPDATE SET
            name = EXCLUDED.name,
            exchange = EXCLUDED.exchange,
            asset_type = EXCLUDED.asset_type,
            priority = EXCLUDED.priority,
            is_active = EXCLUDED.is_active,
            updated_at = NOW()
        """
        with self.connection.cursor() as cur:
            cur.executemany(sql, symbols)
        self.connection.commit()

    def get_active_symbols(self) -> list[dict]:
        sql = """
        SELECT id, ticker, name, exchange, asset_type, priority
        FROM symbols
        WHERE is_active = TRUE
        ORDER BY priority ASC, ticker ASC
        """
        with self.connection.cursor(row_factory=dict_row) as cur:
            cur.execute(sql)
            return list(cur.fetchall())

    def get_symbol_by_ticker(self, ticker: str) -> dict | None:
        sql = """
        SELECT id, ticker, name, exchange, asset_type, priority, is_active
        FROM symbols
        WHERE ticker = %s
        """
        with self.connection.cursor(row_factory=dict_row) as cur:
            cur.execute(sql, (ticker.upper(),))
            row = cur.fetchone()
            return dict(row) if row else None

    def latest_candle_time(self, symbol_id: int, interval: str) -> datetime | None:
        sql = """
        SELECT MAX(datetime) AS max_dt
        FROM candles
        WHERE symbol_id = %s AND interval = %s
        """
        with self.connection.cursor() as cur:
            cur.execute(sql, (symbol_id, interval))
            row = cur.fetchone()
            return row[0] if row and row[0] else None

    def upsert_candles(self, rows: Iterable[CandleRow]) -> int:
        rows = list(rows)
        if not rows:
            return 0

        sql = """
        INSERT INTO candles (symbol_id, datetime, open, high, low, close, volume, interval)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (symbol_id, datetime, interval)
        DO UPDATE SET
            open = EXCLUDED.open,
            high = EXCLUDED.high,
            low = EXCLUDED.low,
            close = EXCLUDED.close,
            volume = EXCLUDED.volume,
            updated_at = NOW()
        """
        params = [
            (
                row.symbol_id,
                row.datetime,
                row.open,
                row.high,
                row.low,
                row.close,
                row.volume,
                row.interval,
            )
            for row in rows
        ]
        with self.connection.cursor() as cur:
            cur.executemany(sql, params)
        self.connection.commit()
        return len(params)

    def record_ingestion_log(
        self,
        symbol_id: int,
        interval: str,
        status: str,
        last_candle_time: datetime | None,
        error_message: str | None = None,
    ) -> None:
        sql = """
        INSERT INTO ingestion_logs (symbol_id, interval, status, last_candle_time, error_message)
        VALUES (%s, %s, %s, %s, %s)
        """
        with self.connection.cursor() as cur:
            cur.execute(sql, (symbol_id, interval, status, last_candle_time, error_message))
        self.connection.commit()

    def get_or_create_daily_usage(self, usage_date: date) -> int:
        sql = """
        INSERT INTO api_usage_daily (usage_date, request_count)
        VALUES (%s, 0)
        ON CONFLICT (usage_date) DO NOTHING
        """
        with self.connection.cursor() as cur:
            cur.execute(sql, (usage_date,))
        self.connection.commit()

        read_sql = "SELECT request_count FROM api_usage_daily WHERE usage_date = %s"
        with self.connection.cursor() as cur:
            cur.execute(read_sql, (usage_date,))
            row = cur.fetchone()
            return int(row[0]) if row else 0

    def increment_daily_usage(self, usage_date: date, count: int = 1) -> int:
        sql = """
        INSERT INTO api_usage_daily (usage_date, request_count)
        VALUES (%s, %s)
        ON CONFLICT (usage_date)
        DO UPDATE SET
            request_count = api_usage_daily.request_count + EXCLUDED.request_count,
            updated_at = NOW()
        RETURNING request_count
        """
        with self.connection.cursor() as cur:
            cur.execute(sql, (usage_date, count))
            row = cur.fetchone()
        self.connection.commit()
        return int(row[0])

    def update_ingestion_state_success(self, symbol_id: int, interval: str, now: datetime) -> None:
        sql = """
        INSERT INTO ingestion_state (symbol_id, interval, consecutive_failures, cooldown_until, last_success_at, last_attempt_at)
        VALUES (%s, %s, 0, NULL, %s, %s)
        ON CONFLICT (symbol_id, interval)
        DO UPDATE SET
            consecutive_failures = 0,
            cooldown_until = NULL,
            last_success_at = EXCLUDED.last_success_at,
            last_attempt_at = EXCLUDED.last_attempt_at,
            updated_at = NOW()
        """
        with self.connection.cursor() as cur:
            cur.execute(sql, (symbol_id, interval, now, now))
        self.connection.commit()

    def update_ingestion_state_failure(
        self,
        symbol_id: int,
        interval: str,
        now: datetime,
        cooldown_until: datetime,
    ) -> int:
        sql = """
        INSERT INTO ingestion_state (symbol_id, interval, consecutive_failures, cooldown_until, last_attempt_at)
        VALUES (%s, %s, 1, %s, %s)
        ON CONFLICT (symbol_id, interval)
        DO UPDATE SET
            consecutive_failures = ingestion_state.consecutive_failures + 1,
            cooldown_until = EXCLUDED.cooldown_until,
            last_attempt_at = EXCLUDED.last_attempt_at,
            updated_at = NOW()
        RETURNING consecutive_failures
        """
        with self.connection.cursor() as cur:
            cur.execute(sql, (symbol_id, interval, cooldown_until, now))
            row = cur.fetchone()
        self.connection.commit()
        return int(row[0])

    def get_cooldown_until(self, symbol_id: int, interval: str) -> datetime | None:
        sql = """
        SELECT cooldown_until
        FROM ingestion_state
        WHERE symbol_id = %s AND interval = %s
        """
        with self.connection.cursor() as cur:
            cur.execute(sql, (symbol_id, interval))
            row = cur.fetchone()
            if not row or row[0] is None:
                return None
            dt = row[0]
            if dt.tzinfo is None:
                return dt.replace(tzinfo=timezone.utc)
            return dt

    def set_cooldown_until(
        self,
        symbol_id: int,
        interval: str,
        now: datetime,
        cooldown_until: datetime,
    ) -> None:
        sql = """
        UPDATE ingestion_state
        SET cooldown_until = %s,
            last_attempt_at = %s,
            updated_at = NOW()
        WHERE symbol_id = %s AND interval = %s
        """
        with self.connection.cursor() as cur:
            cur.execute(sql, (cooldown_until, now, symbol_id, interval))
        self.connection.commit()

    def get_recent_candles(
        self,
        symbol_id: int,
        interval: str,
        limit: int = 50,
    ) -> list[dict]:
        sql = """
        SELECT datetime, open, high, low, close, volume, interval
        FROM candles
        WHERE symbol_id = %s AND interval = %s
        ORDER BY datetime DESC
        LIMIT %s
        """
        with self.connection.cursor(row_factory=dict_row) as cur:
            cur.execute(sql, (symbol_id, interval, limit))
            rows = list(cur.fetchall())
        rows.reverse()
        return rows

    def get_latest_candle(self, symbol_id: int, interval: str) -> dict | None:
        sql = """
        SELECT datetime, open, high, low, close, volume, interval
        FROM candles
        WHERE symbol_id = %s AND interval = %s
        ORDER BY datetime DESC
        LIMIT 1
        """
        with self.connection.cursor(row_factory=dict_row) as cur:
            cur.execute(sql, (symbol_id, interval))
            row = cur.fetchone()
            return dict(row) if row else None

    def get_candles_in_range(
        self,
        symbol_id: int,
        interval: str,
        start: datetime | None,
        end: datetime | None,
        limit: int = 5000,
    ) -> list[dict]:
        clauses = ["symbol_id = %s", "interval = %s"]
        params: list = [symbol_id, interval]

        if start is not None:
            clauses.append("datetime >= %s")
            params.append(start)
        if end is not None:
            clauses.append("datetime <= %s")
            params.append(end)

        where_sql = " AND ".join(clauses)
        sql = f"""
        SELECT datetime, open, high, low, close, volume, interval
        FROM candles
        WHERE {where_sql}
        ORDER BY datetime ASC
        LIMIT %s
        """
        params.append(limit)

        with self.connection.cursor(row_factory=dict_row) as cur:
            cur.execute(sql, params)
            return list(cur.fetchall())
