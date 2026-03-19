from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from psycopg import connect
from psycopg.rows import dict_row


@dataclass
class PostgresCandleStore:
    dsn: str
    connect_timeout_seconds: int = 2

    def _conn(self):
        return connect(self.dsn, connect_timeout=self.connect_timeout_seconds)

    def get_symbol_id(self, ticker: str) -> int | None:
        sql = "SELECT id FROM symbols WHERE ticker = %s AND is_active = TRUE"
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (ticker.upper(),))
                row = cur.fetchone()
                return int(row[0]) if row else None

    def get_candles(
        self,
        ticker: str,
        interval: str = "1day",
        limit: int = 600,
        end: datetime | None = None,
    ) -> list[dict[str, Any]]:
        symbol_id = self.get_symbol_id(ticker)
        if symbol_id is None:
            return []

        clauses = ["symbol_id = %s", "interval = %s"]
        params: list[Any] = [symbol_id, interval]
        if end is not None:
            clauses.append("datetime <= %s")
            params.append(end)

        sql = f"""
        SELECT datetime, open, high, low, close, volume
        FROM candles
        WHERE {' AND '.join(clauses)}
        ORDER BY datetime DESC
        LIMIT %s
        """
        params.append(limit)

        with self._conn() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(sql, params)
                rows = list(cur.fetchall())

        rows.reverse()
        return rows
