from __future__ import annotations

import os
from pathlib import Path

import pandas as pd

import db as sqlite_db
from strategy_ml.db import PostgresCandleStore


class CandleDataLoader:
    """Loads candles from PostgreSQL, with SQLite fallback for local demo mode."""

    def __init__(self, postgres_dsn: str | None = None):
        self.postgres_dsn = postgres_dsn or os.getenv("POSTGRES_DSN")
        self._store = PostgresCandleStore(self.postgres_dsn) if self.postgres_dsn else None

    def load_candles(
        self,
        ticker: str,
        interval: str = "1day",
        limit: int = 600,
    ) -> pd.DataFrame:
        ticker = ticker.upper()
        if self._store is not None:
            try:
                rows = self._store.get_candles(ticker=ticker, interval=interval, limit=limit)
                if rows:
                    df = pd.DataFrame(rows)
                    df["datetime"] = pd.to_datetime(df["datetime"], utc=True)
                    return df
            except Exception:
                # Fall back to SQLite snapshots when Postgres is unavailable.
                pass

        # Demo fallback keeps API behavior stable for local runs without PostgreSQL.
        history = sqlite_db.get_ohlc(ticker, limit=min(limit, 3650))
        if not history:
            return pd.DataFrame(columns=["datetime", "open", "high", "low", "close", "volume"])

        df = pd.DataFrame(history)
        df["datetime"] = pd.to_datetime(df["date"], utc=True)
        df = df.drop(columns=["date"]) if "date" in df.columns else df
        return df[["datetime", "open", "high", "low", "close", "volume"]]

    def load_universe(
        self,
        tickers: list[str],
        interval: str = "1day",
        limit: int = 600,
    ) -> dict[str, pd.DataFrame]:
        out: dict[str, pd.DataFrame] = {}
        for ticker in tickers:
            out[ticker.upper()] = self.load_candles(ticker=ticker, interval=interval, limit=limit)
        return out
