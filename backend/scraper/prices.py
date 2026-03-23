"""
Background price scraper — fetches OHLC from Twelve Data every N minutes
and writes to Postgres. Runs as a daemon thread.
"""

from __future__ import annotations

import threading
import time
import traceback
from datetime import datetime

import httpx
from universe import DASHBOARD_TICKERS

_thread: threading.Thread | None = None


def _map_symbol(ticker: str) -> str:
    return ticker.upper()


def _api_get(client: httpx.Client, url: str, params: dict) -> dict:
    """Make one Twelve Data API call. Raises on 429 with a clear message."""
    resp = client.get(url, params=params)
    resp.raise_for_status()
    data = resp.json()
    if isinstance(data, dict) and data.get("code") == 429:
        raise RuntimeError(f"Rate limited (429): {data.get('message', '')}")
    if isinstance(data, dict) and data.get("status") == "error":
        raise ValueError(f"API error: {data.get('message', data)}")
    return data


def _parse_api_datetime(value: str) -> datetime:
    # Twelve Data returns naive "YYYY-MM-DD HH:MM:SS" for time_series rows.
    # If the string ever carries a timezone suffix (e.g. "Z"), strip it so the
    # result is always naive — comparisons against latest_dt.replace(tzinfo=None)
    # would raise TypeError if this returned an aware datetime.
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return dt.replace(tzinfo=None)


def fetch_ticker(ticker: str, api_key: str, outputsize: int = 1825) -> tuple[float, list[dict], float]:
    symbol = _map_symbol(ticker)
    client = httpx.Client(timeout=15)

    # 1st API credit — current price
    price_data = _api_get(client, "https://api.twelvedata.com/price", {"symbol": symbol, "apikey": api_key})
    price = float(price_data["price"])

    time.sleep(9)  # stay under 8 credits/min — wait between the two calls for this ticker

    # 2nd API credit — OHLC history
    ohlc_data = _api_get(
        client,
        "https://api.twelvedata.com/time_series",
        {"symbol": symbol, "interval": "1day", "outputsize": outputsize, "apikey": api_key},
    )
    if "values" not in ohlc_data:
        raise ValueError(f"No OHLC values for {ticker}: {ohlc_data}")

    bars = [
        {
            "date": item["datetime"],
            "open": float(item["open"]),
            "high": float(item["high"]),
            "low": float(item["low"]),
            "close": float(item["close"]),
            "volume": int(item["volume"]),
        }
        for item in reversed(ohlc_data["values"])
    ]

    change_pct = 0.0
    if len(bars) >= 2 and bars[-2]["close"]:
        change_pct = round(((price - bars[-2]["close"]) / bars[-2]["close"]) * 100, 2)

    client.close()
    return price, bars, change_pct


def scrape_once(tickers: list[str] | None = None, *, full_history: bool = False):
    from config import settings
    import db

    api_key = settings.twelve_data_api_key
    tickers = tickers or DASHBOARD_TICKERS
    ohlc_outputsize = settings.ohlc_outputsize if full_history else min(settings.ohlc_outputsize, 5)
    started = time.time()
    mode = "full backfill" if full_history else "incremental"
    print(f"[scraper] Starting {mode} scrape for {len(tickers)} tickers...")

    ok, failed = 0, 0
    for ticker in tickers:
        try:
            latest_dt = db.get_latest_candle_datetime(ticker, interval="1day")
            price, bars, change_pct = fetch_ticker(ticker, api_key, outputsize=ohlc_outputsize)
            if latest_dt is None:
                bars_to_write = bars
                new_bars = len(bars)
            else:
                bars_to_write = [b for b in bars if _parse_api_datetime(b["date"]) >= latest_dt.replace(tzinfo=None)]
                new_bars = sum(1 for b in bars if _parse_api_datetime(b["date"]) > latest_dt.replace(tzinfo=None))
            db.upsert_price(ticker, price, change_pct)
            db.upsert_ohlc(ticker, bars_to_write)
            print(
                f"  [scraper] {ticker}: ${price:.2f} ({change_pct:+.2f}%) "
                f"— fetched {len(bars)} bars, wrote {len(bars_to_write)} (new {new_bars})"
            )
            ok += 1
            time.sleep(9)  # 9s between tickers so we stay under 8 credits/min
        except RuntimeError as e:
            # 429 — back off a full minute then retry this ticker once
            print(f"  [scraper] {ticker} rate limited, waiting 60s...")
            time.sleep(60)
            try:
                latest_dt = db.get_latest_candle_datetime(ticker, interval="1day")
                price, bars, change_pct = fetch_ticker(ticker, api_key, outputsize=ohlc_outputsize)
                if latest_dt is None:
                    bars_to_write = bars
                    new_bars = len(bars)
                else:
                    bars_to_write = [b for b in bars if _parse_api_datetime(b["date"]) >= latest_dt.replace(tzinfo=None)]
                    new_bars = sum(1 for b in bars if _parse_api_datetime(b["date"]) > latest_dt.replace(tzinfo=None))
                db.upsert_price(ticker, price, change_pct)
                db.upsert_ohlc(ticker, bars_to_write)
                print(
                    f"  [scraper] {ticker}: ${price:.2f} ({change_pct:+.2f}%) "
                    f"— fetched {len(bars)} bars, wrote {len(bars_to_write)} (new {new_bars}) (retry ok)"
                )
                ok += 1
            except Exception as e2:
                print(f"  [scraper] {ticker} FAILED after retry: {e2}")
                failed += 1
        except Exception as e:
            print(f"  [scraper] {ticker} FAILED: {e}")
            traceback.print_exc()
            failed += 1

    elapsed = round(time.time() - started)
    print(f"[scraper] Done — {ok} ok, {failed} failed, took {elapsed}s")


def _run_loop(interval_seconds: int):
    while True:
        try:
            time.sleep(interval_seconds)
            print(f"[scraper] Scheduled refresh triggered")
            scrape_once(full_history=False)
        except Exception:
            traceback.print_exc()


def _missing_tickers(all_tickers: list[str]) -> list[str]:
    """Return tickers that have no candles yet."""
    import db
    existing = db.get_tickers_with_candles()
    return [t for t in all_tickers if t.upper() not in existing]


def start_background_scraper():
    global _thread
    if _thread is not None and _thread.is_alive():
        print("[scraper] Already running, skipping start.")
        return

    from config import settings

    interval = settings.dashboard_refresh_minutes * 60
    missing = _missing_tickers(DASHBOARD_TICKERS)

    if missing:
        print(f"[scraper] Missing candles for {missing} — fetching now...")
        scrape_once(missing, full_history=True)
    else:
        print("[scraper] All tickers already have price data — skipping initial scrape.")

    print(f"[scraper] Background thread started — refreshes every {settings.dashboard_refresh_minutes} min")
    _thread = threading.Thread(target=_run_loop, args=(interval,), daemon=True)
    _thread.start()
