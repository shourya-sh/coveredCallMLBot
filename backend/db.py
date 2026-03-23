"""
Database layer — Postgres only (Supabase).

All app data lives here: prices, OHLC candles, options chains.
No SQLite.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from typing import Any, Optional

from psycopg import connect
from psycopg.rows import dict_row


def _dsn() -> str:
    from config import settings
    if not settings.postgres_dsn:
        raise RuntimeError("POSTGRES_DSN is not set in .env")
    return settings.postgres_dsn


@contextmanager
def _conn():
    with connect(_dsn(), row_factory=dict_row, connect_timeout=5, prepare_threshold=None) as conn:
        yield conn


# ── Price snapshots ───────────────────────────────────────────────────────────

def upsert_price(ticker: str, price: float, change_pct: float):
    with _conn() as conn:
        conn.execute(
            """
            INSERT INTO prices (ticker, price, change_pct, updated_at)
            VALUES (%s, %s, %s, NOW())
            ON CONFLICT (ticker) DO UPDATE SET
                price = EXCLUDED.price,
                change_pct = EXCLUDED.change_pct,
                updated_at = NOW()
            """,
            (ticker.upper(), price, change_pct),
        )


def get_price(ticker: str) -> Optional[dict]:
    with _conn() as conn:
        return conn.execute(
            "SELECT ticker, price, change_pct, updated_at FROM prices WHERE ticker = %s",
            (ticker.upper(),),
        ).fetchone()


def get_all_prices() -> list[dict]:
    with _conn() as conn:
        return conn.execute("SELECT ticker, price, change_pct, updated_at FROM prices").fetchall()


def get_tickers_with_candles() -> set[str]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT DISTINCT s.ticker FROM candles c JOIN symbols s ON s.id = c.symbol_id"
        ).fetchall()
    return {r["ticker"] for r in rows}


def last_updated_any() -> Optional[str]:
    with _conn() as conn:
        row = conn.execute("SELECT MAX(updated_at) AS ts FROM prices").fetchone()
        return row["ts"].isoformat() if row and row["ts"] else None


# ── OHLC candles ──────────────────────────────────────────────────────────────

def upsert_ohlc(ticker: str, bars: list[dict]):
    """bars: list of {date, open, high, low, close, volume}"""
    if not bars:
        return
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO candles (symbol_id, interval, datetime, open, high, low, close, volume)
                SELECT s.id, '1day', %s::timestamptz, %s, %s, %s, %s, %s
                FROM symbols s WHERE s.ticker = %s
                ON CONFLICT (symbol_id, interval, datetime) DO UPDATE SET
                    open   = EXCLUDED.open,
                    high   = EXCLUDED.high,
                    low    = EXCLUDED.low,
                    close  = EXCLUDED.close,
                    volume = EXCLUDED.volume
                """,
                [
                    (b["date"], b["open"], b["high"], b["low"], b["close"], b["volume"], ticker.upper())
                    for b in bars
                ],
            )


def get_ohlc(ticker: str, limit: int = 30) -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            """
            SELECT c.datetime AS date, c.open, c.high, c.low, c.close, c.volume
            FROM candles c
            JOIN symbols s ON s.id = c.symbol_id
            WHERE s.ticker = %s AND c.interval = '1day'
            ORDER BY c.datetime DESC
            LIMIT %s
            """,
            (ticker.upper(), limit),
        ).fetchall()
    rows.reverse()
    return [dict(r) for r in rows]


def load_candles(ticker: str, interval: str = "1day", limit: int = 1825) -> list[dict[str, Any]]:
    """Load candles for ML training/inference."""
    with _conn() as conn:
        rows = conn.execute(
            """
            SELECT c.datetime, c.open, c.high, c.low, c.close, c.volume
            FROM candles c
            JOIN symbols s ON s.id = c.symbol_id
            WHERE s.ticker = %s AND c.interval = %s
            ORDER BY c.datetime DESC
            LIMIT %s
            """,
            (ticker.upper(), interval, limit),
        ).fetchall()
    rows.reverse()
    return [dict(r) for r in rows]


# ── Options chain cache ───────────────────────────────────────────────────────

def upsert_options_chain(ticker: str, contracts: list, source: str = "nasdaq"):
    if not contracts:
        return
    ticker = ticker.upper()
    now = datetime.now()
    with _conn() as conn:
        conn.execute("DELETE FROM options_cache WHERE ticker = %s", (ticker,))
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO options_cache (
                    ticker, expiration, contract_type, strike,
                    bid, ask, last_price, volume, open_interest,
                    implied_volatility, delta, updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (ticker, expiration, contract_type, strike) DO UPDATE SET
                    bid = EXCLUDED.bid, ask = EXCLUDED.ask,
                    last_price = EXCLUDED.last_price,
                    volume = EXCLUDED.volume, open_interest = EXCLUDED.open_interest,
                    implied_volatility = EXCLUDED.implied_volatility,
                    delta = EXCLUDED.delta, updated_at = EXCLUDED.updated_at
                """,
                [
                    (
                        ticker,
                        c.expiration.date(),
                        c.contract_type,
                        c.strike,
                        c.bid, c.ask, c.last,
                        c.volume, c.open_interest,
                        c.implied_volatility, c.delta,
                        now,
                    )
                    for c in contracts
                ],
            )
        conn.execute(
            """
            INSERT INTO options_cache_meta (ticker, source, updated_at)
            VALUES (%s, %s, %s)
            ON CONFLICT (ticker) DO UPDATE SET
                source = EXCLUDED.source, updated_at = EXCLUDED.updated_at
            """,
            (ticker, source, now),
        )


def get_options_chain(ticker: str) -> list[dict]:
    with _conn() as conn:
        return [
            dict(r) for r in conn.execute(
                """
                SELECT ticker, expiration, contract_type, strike,
                       bid, ask, last_price AS last, volume, open_interest,
                       implied_volatility, delta, updated_at
                FROM options_cache
                WHERE ticker = %s
                ORDER BY expiration, contract_type, strike
                """,
                (ticker.upper(),),
            ).fetchall()
        ]


def get_options_chain_updated_at(ticker: str) -> Optional[str]:
    with _conn() as conn:
        row = conn.execute(
            "SELECT MAX(updated_at) AS ts FROM options_cache WHERE ticker = %s",
            (ticker.upper(),),
        ).fetchone()
    return row["ts"].isoformat() if row and row["ts"] else None


def get_options_chain_source(ticker: str) -> Optional[str]:
    with _conn() as conn:
        row = conn.execute(
            "SELECT source FROM options_cache_meta WHERE ticker = %s",
            (ticker.upper(),),
        ).fetchone()
    return row["source"] if row else None
