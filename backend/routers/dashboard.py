from __future__ import annotations

import time
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, HTTPException

import db
from scraper.options import OptionContract, NasdaqOptionsScraper, get_scraper
from ml.predict import StrategyPredictor
from ml.types import StrategyClass

router = APIRouter()

DASHBOARD_TICKERS = ["SPY", "QQQ", "IWM", "AAPL", "TSLA", "NVDA", "AMZN", "MSFT", "META", "SPX"]
OPTIONS_CACHE_MAX_AGE_MINUTES = 30

_predictor: StrategyPredictor | None = None
_predictor_mtime: float | None = None
_dashboard_cache: dict | None = None
_dashboard_cache_expires_at: float = 0.0


def _get_predictor() -> StrategyPredictor | None:
    global _predictor, _predictor_mtime
    model_path = Path(__file__).resolve().parent.parent / "ml" / "artifacts" / "options_strategy_model.joblib"
    if not model_path.exists():
        return None
    mtime = model_path.stat().st_mtime
    if _predictor is not None and _predictor_mtime == mtime:
        return _predictor
    try:
        _predictor = StrategyPredictor(model_path=str(model_path))
        _predictor_mtime = mtime
    except Exception as e:
        print(f"[dashboard] Failed to load model: {e}")
        _predictor = None
    return _predictor


def _rows_to_contracts(rows: list[dict]) -> list[OptionContract]:
    contracts = []
    for row in rows:
        try:
            exp = datetime.fromisoformat(row["expiration"])
            contracts.append(OptionContract(
                ticker=row["ticker"],
                contract_type=row["contract_type"],
                strike=float(row["strike"]),
                expiration=exp,
                bid=float(row.get("bid") or 0),
                ask=float(row.get("ask") or 0),
                last=float(row["last"]) if row.get("last") is not None else None,
                volume=int(row.get("volume") or 0),
                open_interest=int(row.get("open_interest") or 0),
                implied_volatility=float(row["implied_volatility"]) if row.get("implied_volatility") is not None else None,
                delta=float(row["delta"]) if row.get("delta") is not None else None,
            ))
        except Exception:
            continue
    return contracts


def _get_options(ticker: str, scraper: NasdaqOptionsScraper, force_refresh: bool = False) -> tuple[list[OptionContract], str]:
    rows = db.get_options_chain(ticker)
    cached = _rows_to_contracts(rows)
    updated_at_str = db.get_options_chain_updated_at(ticker)
    source = db.get_options_chain_source(ticker) or "unknown"

    cache_fresh = False
    if updated_at_str:
        age = datetime.now() - datetime.fromisoformat(updated_at_str)
        cache_fresh = age <= timedelta(minutes=OPTIONS_CACHE_MAX_AGE_MINUTES)

    if not force_refresh and cached and cache_fresh:
        return cached, f"cache:{source}"

    try:
        chain = scraper.get_all_expirations(ticker, max_expirations=2, include_puts=True)
        contracts = [c for bucket in chain.values() for c in bucket]
        if contracts:
            db.upsert_options_chain(ticker, contracts, source="nasdaq")
            return contracts, "live:nasdaq"
    except Exception:
        if cached:
            return cached, f"stale:{source}"
        raise

    return cached or [], f"stale:{source}" if cached else "empty"


def _snapshot(ticker: str) -> dict:
    row = db.get_price(ticker)
    return {
        "ticker": ticker,
        "price": row["price"] if row else 0.0,
        "change_pct": row["change_pct"] if row else 0.0,
        "history": db.get_ohlc(ticker, limit=30),
        "last_updated": row["updated_at"] if row else None,
    }


def _no_model_analysis(ticker: str) -> dict:
    return {
        "ticker": ticker,
        "top_strategy": StrategyClass.NO_TRADE.value,
        "confidence": 0.0,
        "probabilities": {StrategyClass.NO_TRADE.value: 1.0},
        "risk_flags": ["model_not_trained"],
        "execution_plan": None,
    }


@router.get("/dashboard/stocks")
def dashboard_stocks():
    global _dashboard_cache, _dashboard_cache_expires_at

    from config import settings
    now = time.time()
    if _dashboard_cache is not None and now < _dashboard_cache_expires_at:
        return _dashboard_cache

    predictor = _get_predictor()
    scraper = get_scraper()
    stocks = []

    for ticker in DASHBOARD_TICKERS:
        snapshot = _snapshot(ticker)
        if predictor is None:
            snapshot["analysis"] = _no_model_analysis(ticker)
        else:
            try:
                contracts, chain_source = _get_options(ticker, scraper)
            except Exception:
                contracts, chain_source = [], "unavailable"

            analysis = predictor.predict(ticker, contracts=contracts)
            analysis["options_chain_source"] = chain_source
            analysis["options_chain_updated_at"] = db.get_options_chain_updated_at(ticker)
            snapshot["analysis"] = analysis

        stocks.append(snapshot)

    payload = {"stocks": stocks, "last_updated": db.last_updated_any()}
    _dashboard_cache = payload
    _dashboard_cache_expires_at = now + settings.dashboard_cache_ttl_seconds
    return payload


@router.get("/stock/{ticker}")
def single_stock(ticker: str):
    ticker = ticker.strip().upper()
    if ticker not in DASHBOARD_TICKERS:
        raise HTTPException(status_code=400, detail=f"{ticker} not in dashboard universe")

    snapshot = _snapshot(ticker)
    predictor = _get_predictor()

    if predictor is None:
        return {**snapshot, "analysis": _no_model_analysis(ticker)}

    scraper = get_scraper()
    try:
        contracts, chain_source = _get_options(ticker, scraper, force_refresh=False)
    except Exception:
        contracts, chain_source = [], "unavailable"

    analysis = predictor.predict(ticker, contracts=contracts)
    analysis["options_chain_source"] = chain_source
    analysis["options_chain_updated_at"] = db.get_options_chain_updated_at(ticker)
    return {**snapshot, "analysis": analysis}
