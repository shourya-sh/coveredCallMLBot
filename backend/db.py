"""
SQLite persistent store for stock prices and OHLC history.
Data survives server restarts — the frontend always has prices instantly.
"""

import sqlite3
import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

DB_PATH = Path(__file__).parent / "stocks.db"

_local = threading.local()


def _get_conn() -> sqlite3.Connection:
    """One connection per thread (SQLite limitation)."""
    if not hasattr(_local, "conn"):
        _local.conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        _local.conn.row_factory = sqlite3.Row
        _local.conn.execute("PRAGMA journal_mode=WAL")
    return _local.conn


def init_db():
    """Create tables if they don't exist."""
    conn = _get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS stock_prices (
            ticker      TEXT PRIMARY KEY,
            price       REAL NOT NULL,
            change_pct  REAL NOT NULL DEFAULT 0,
            updated_at  TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS ohlc_history (
            ticker  TEXT NOT NULL,
            date    TEXT NOT NULL,
            open    REAL,
            high    REAL,
            low     REAL,
            close   REAL,
            volume  INTEGER,
            PRIMARY KEY (ticker, date)
        );

        CREATE TABLE IF NOT EXISTS options_chain_cache (
            ticker              TEXT NOT NULL,
            expiration          TEXT NOT NULL,
            contract_type       TEXT NOT NULL,
            strike              REAL NOT NULL,
            bid                 REAL NOT NULL DEFAULT 0,
            ask                 REAL NOT NULL DEFAULT 0,
            last                REAL,
            volume              INTEGER NOT NULL DEFAULT 0,
            open_interest       INTEGER NOT NULL DEFAULT 0,
            implied_volatility  REAL,
            delta               REAL,
            updated_at          TEXT NOT NULL,
            PRIMARY KEY (ticker, expiration, contract_type, strike)
        );

        CREATE TABLE IF NOT EXISTS options_chain_meta (
            ticker      TEXT PRIMARY KEY,
            source      TEXT NOT NULL,
            updated_at  TEXT NOT NULL
        );
    """)
    conn.commit()


# ── Writes ──────────────────────────────────────────────────────────────────

def upsert_price(ticker: str, price: float, change_pct: float):
    conn = _get_conn()
    conn.execute(
        """INSERT INTO stock_prices (ticker, price, change_pct, updated_at)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(ticker) DO UPDATE SET
               price=excluded.price,
               change_pct=excluded.change_pct,
               updated_at=excluded.updated_at""",
        (ticker, price, change_pct, datetime.now().isoformat()),
    )
    conn.commit()


def upsert_ohlc(ticker: str, bars: list[dict]):
    """bars: list of {date, open, high, low, close, volume}"""
    conn = _get_conn()
    conn.executemany(
        """INSERT INTO ohlc_history (ticker, date, open, high, low, close, volume)
           VALUES (?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(ticker, date) DO UPDATE SET
               open=excluded.open, high=excluded.high,
               low=excluded.low, close=excluded.close,
               volume=excluded.volume""",
        [
            (ticker, b["date"], b["open"], b["high"], b["low"], b["close"], b["volume"])
            for b in bars
        ],
    )
    conn.commit()


def upsert_option_chain(ticker: str, contracts: list, source: str = "yahoo"):
    """Store option chain snapshot for ticker; replaces previous snapshot rows."""
    conn = _get_conn()
    now = datetime.now().isoformat()
    conn.execute("DELETE FROM options_chain_cache WHERE ticker=?", (ticker,))
    conn.executemany(
        """INSERT INTO options_chain_cache (
               ticker, expiration, contract_type, strike,
               bid, ask, last, volume, open_interest,
               implied_volatility, delta, updated_at
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [
            (
                ticker,
                c.expiration.isoformat(),
                c.contract_type,
                c.strike,
                c.bid,
                c.ask,
                c.last,
                c.volume,
                c.open_interest,
                c.implied_volatility,
                c.delta,
                now,
            )
            for c in contracts
        ],
    )
    conn.execute(
        """INSERT INTO options_chain_meta (ticker, source, updated_at)
           VALUES (?, ?, ?)
           ON CONFLICT(ticker) DO UPDATE SET
             source=excluded.source,
             updated_at=excluded.updated_at""",
        (ticker, source, now),
    )
    conn.commit()


# ── Reads ───────────────────────────────────────────────────────────────────

def get_price(ticker: str) -> Optional[dict]:
    conn = _get_conn()
    row = conn.execute(
        "SELECT ticker, price, change_pct, updated_at FROM stock_prices WHERE ticker=?",
        (ticker,),
    ).fetchone()
    if row is None:
        return None
    return dict(row)


def get_all_prices() -> list[dict]:
    conn = _get_conn()
    rows = conn.execute("SELECT ticker, price, change_pct, updated_at FROM stock_prices").fetchall()
    return [dict(r) for r in rows]


def get_ohlc(ticker: str, limit: int = 30) -> list[dict]:
    conn = _get_conn()
    rows = conn.execute(
        "SELECT date, open, high, low, close, volume FROM ohlc_history WHERE ticker=? ORDER BY date DESC LIMIT ?",
        (ticker, limit),
    ).fetchall()
    out = [dict(r) for r in rows]
    out.reverse()
    return out


def last_updated(ticker: str) -> Optional[str]:
    conn = _get_conn()
    row = conn.execute("SELECT updated_at FROM stock_prices WHERE ticker=?", (ticker,)).fetchone()
    return row["updated_at"] if row else None


def last_updated_any() -> Optional[str]:
    conn = _get_conn()
    row = conn.execute("SELECT MAX(updated_at) as ts FROM stock_prices").fetchone()
    return row["ts"] if row else None


def get_option_chain(ticker: str) -> list[dict]:
    conn = _get_conn()
    rows = conn.execute(
        """SELECT ticker, expiration, contract_type, strike,
                  bid, ask, last, volume, open_interest,
                  implied_volatility, delta, updated_at
           FROM options_chain_cache
           WHERE ticker=?
           ORDER BY expiration ASC, contract_type ASC, strike ASC""",
        (ticker,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_option_chain_last_updated(ticker: str) -> Optional[str]:
    conn = _get_conn()
    row = conn.execute(
        "SELECT MAX(updated_at) as ts FROM options_chain_cache WHERE ticker=?",
        (ticker,),
    ).fetchone()
    return row["ts"] if row and row["ts"] else None


def get_option_chain_source(ticker: str) -> Optional[str]:
    conn = _get_conn()
    row = conn.execute(
        "SELECT source FROM options_chain_meta WHERE ticker=?",
        (ticker,),
    ).fetchone()
    return row["source"] if row and row["source"] else None
