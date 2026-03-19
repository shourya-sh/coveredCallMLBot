"""
Background scraper — fetches prices from Twelve Data every INTERVAL_SECONDS
and writes them to SQLite. Runs in a daemon thread so the server stays responsive.
"""

import os
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

# Ensure .env is loaded from backend/ regardless of cwd
load_dotenv(Path(__file__).parent / ".env")

from data_ingestion.twelve_data_client import TwelveDataClient, TwelveDataConfig
from db import init_db, upsert_price, upsert_ohlc, last_updated_any

try:
    import yfinance as yf
except Exception:
    yf = None

_refresh_minutes = int(os.getenv("DASHBOARD_REFRESH_MINUTES", "15"))
if _refresh_minutes < 10 or _refresh_minutes > 15:
    _refresh_minutes = 15
INTERVAL_SECONDS = _refresh_minutes * 60
DASHBOARD_TICKERS = ["SPY", "QQQ", "IWM", "AAPL", "TSLA", "NVDA", "AMZN", "MSFT", "META", "SPX"]
DEFAULT_OHLC_OUTPUTSIZE = int(os.getenv("DASHBOARD_OHLC_OUTPUTSIZE", "365"))


def _build_client() -> TwelveDataClient | None:
    key = os.getenv("TWELVE_DATA_API_KEY")
    if not key:
        return None
    return TwelveDataClient(TwelveDataConfig(api_key=key))


def _map_yfinance_symbol(ticker: str) -> str:
    if ticker.upper() == "SPX":
        return "^GSPC"
    return ticker.upper()


def _fetch_from_yfinance(ticker: str) -> tuple[float, list[dict], float]:
    if yf is None:
        raise RuntimeError("yfinance is not available")

    symbol = _map_yfinance_symbol(ticker)
    hist = yf.Ticker(symbol).history(period=f"{max(30, DEFAULT_OHLC_OUTPUTSIZE)}d", interval="1d", auto_adjust=False)
    if hist is None or hist.empty:
        raise RuntimeError(f"No yfinance history for {ticker}")

    bars = []
    for dt, row in hist.iterrows():
        bars.append(
            {
                "date": dt.strftime("%Y-%m-%d"),
                "open": float(row.get("Open", 0.0) or 0.0),
                "high": float(row.get("High", 0.0) or 0.0),
                "low": float(row.get("Low", 0.0) or 0.0),
                "close": float(row.get("Close", 0.0) or 0.0),
                "volume": int(row.get("Volume", 0) or 0),
            }
        )

    if not bars:
        raise RuntimeError(f"No yfinance bars for {ticker}")

    price = bars[-1]["close"]
    prev_close = bars[-2]["close"] if len(bars) > 1 else price
    change_pct = round(((price - prev_close) / prev_close) * 100, 2) if prev_close else 0.0
    return price, bars, change_pct


def _fetch_from_twelve_data(client: TwelveDataClient, ticker: str) -> tuple[float, list[dict], float]:
    price_data = client.get_current_price(ticker)
    price = price_data.price
    ohlc = client.get_ohlc_data(ticker, interval="1day", outputsize=DEFAULT_OHLC_OUTPUTSIZE)
    bars = [
        {
            "date": bar.date.strftime("%Y-%m-%d"),
            "open": bar.open,
            "high": bar.high,
            "low": bar.low,
            "close": bar.close,
            "volume": bar.volume,
        }
        for bar in ohlc
    ]

    change_pct = 0.0
    if len(bars) >= 2:
        prev_close = bars[-2]["close"] if bars[-2]["close"] else bars[-1]["close"]
        if prev_close:
            change_pct = round(((price - prev_close) / prev_close) * 100, 2)

    return price, bars, change_pct


def scrape_once(tickers: list[str] | None = None):
    """Fetch latest prices + daily OHLC and store in DB."""
    client = _build_client()
    tickers = tickers or DASHBOARD_TICKERS
    print(f"[scraper] Refreshing {len(tickers)} tickers...")

    for ticker in tickers:
        try:
            source = "yfinance"
            try:
                price, bars, change_pct = _fetch_from_yfinance(ticker)
            except Exception:
                if client is None:
                    raise
                source = "twelve_data"
                price, bars, change_pct = _fetch_from_twelve_data(client, ticker)

            upsert_price(ticker, price, change_pct)
            upsert_ohlc(ticker, bars)
            print(f"  [scraper] {ticker}: ${price:.2f} ({change_pct:+.2f}%) via {source}")

            if source == "twelve_data":
                # Twelve Data free-tier safety pacing.
                time.sleep(8)

        except Exception as e:
            print(f"  [scraper] {ticker} FAILED: {e}")
            traceback.print_exc()


def _seed_demo_data(tickers: list[str]):
    """When no API key, populate DB with demo data so the app still works."""
    from demo_mode import DemoTwelveDataClient
    client = DemoTwelveDataClient()
    for ticker in tickers:
        try:
            price_data = client.get_current_price(ticker)
            price = price_data.price
            ohlc = client.get_ohlc_data(ticker, interval="1day", outputsize=DEFAULT_OHLC_OUTPUTSIZE)
            bars = [
                {
                    "date": bar.date.strftime("%Y-%m-%d"),
                    "open": bar.open,
                    "high": bar.high,
                    "low": bar.low,
                    "close": bar.close,
                    "volume": bar.volume,
                }
                for bar in ohlc
            ]
            change_pct = 0.0
            if len(bars) >= 2:
                prev = bars[-2]["close"]
                if prev:
                    change_pct = round(((price - prev) / prev) * 100, 2)
            upsert_price(ticker, price, change_pct)
            upsert_ohlc(ticker, bars)
        except Exception:
            pass


def _run_loop():
    """Blocking loop — meant to run inside a daemon thread."""
    while True:
        try:
            scrape_once()
        except Exception:
            traceback.print_exc()
        time.sleep(INTERVAL_SECONDS)


_thread: threading.Thread | None = None


def start_background_scraper():
    """Start the scraper daemon. Safe to call multiple times."""
    global _thread
    if _thread is not None and _thread.is_alive():
        return

    init_db()

    # If DB is empty, do one initial scrape synchronously so data is ready fast
    ts = last_updated_any()
    if ts is None:
        print("[scraper] DB is empty — doing initial fetch now...")
        scrape_once()
    else:
        print(f"[scraper] DB already has data (last update: {ts}). Will refresh in background.")

    _thread = threading.Thread(target=_run_loop, daemon=True)
    _thread.start()
    print(f"[scraper] Background thread started — refreshing every {INTERVAL_SECONDS // 60} min")
