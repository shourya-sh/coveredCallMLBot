from __future__ import annotations

import os
import math
from datetime import datetime, timedelta

import db
from data_ingestion.options_scraper import OptionContract, YahooFinanceOptionsScraper


OPTIONS_CACHE_MAX_AGE_MINUTES = int(os.getenv("OPTIONS_CACHE_MAX_AGE_MINUTES", "30"))
OPTIONS_ALLOW_SYNTHETIC_FALLBACK = os.getenv("OPTIONS_ALLOW_SYNTHETIC_FALLBACK", "false").lower() == "true"


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _rows_to_contracts(rows: list[dict]) -> list[OptionContract]:
    contracts: list[OptionContract] = []
    for row in rows:
        exp = _parse_dt(row.get("expiration"))
        if exp is None:
            continue
        contracts.append(
            OptionContract(
                ticker=row["ticker"],
                contract_type=row["contract_type"],
                strike=float(row["strike"]),
                expiration=exp,
                bid=float(row.get("bid") or 0.0),
                ask=float(row.get("ask") or 0.0),
                last=float(row["last"]) if row.get("last") is not None else None,
                volume=int(row.get("volume") or 0),
                open_interest=int(row.get("open_interest") or 0),
                implied_volatility=float(row["implied_volatility"]) if row.get("implied_volatility") is not None else None,
                delta=float(row["delta"]) if row.get("delta") is not None else None,
            )
        )
    return contracts


def _estimate_hist_vol_from_db(ticker: str) -> float:
    rows = db.get_ohlc(ticker, limit=90)
    closes = [float(r.get("close", 0.0) or 0.0) for r in rows if float(r.get("close", 0.0) or 0.0) > 0]
    if len(closes) < 20:
        return 0.28

    log_returns = []
    for i in range(1, len(closes)):
        prev = closes[i - 1]
        curr = closes[i]
        if prev > 0 and curr > 0:
            log_returns.append(math.log(curr / prev))

    if len(log_returns) < 10:
        return 0.28

    mean = sum(log_returns) / len(log_returns)
    var = sum((r - mean) ** 2 for r in log_returns) / max(1, len(log_returns) - 1)
    daily_vol = math.sqrt(var)
    return max(0.12, min(0.95, daily_vol * math.sqrt(252)))


def _build_synthetic_chain(ticker: str) -> list[OptionContract]:
    price_row = db.get_price(ticker)
    spot = float(price_row["price"]) if price_row and price_row.get("price") else 0.0
    if spot <= 0:
        return []

    hist_vol = _estimate_hist_vol_from_db(ticker)
    moneyness_offsets = [-0.10, -0.07, -0.04, -0.02, 0.00, 0.02, 0.04, 0.07, 0.10]
    expiries = [7, 14]
    contracts: list[OptionContract] = []

    for dte in expiries:
        expiration = datetime.now() + timedelta(days=dte)
        expected_move = spot * hist_vol * math.sqrt(dte / 365.0)
        extrinsic_base = max(0.15, expected_move * 0.45)

        for offset in moneyness_offsets:
            strike = round(spot * (1 + offset), 2)
            liquidity = int(max(10, 800 - abs(offset) * 5000))
            extrinsic = max(0.05, extrinsic_base * max(0.25, 1.0 - abs(offset) * 4.0))

            call_intrinsic = max(0.0, spot - strike)
            put_intrinsic = max(0.0, strike - spot)

            call_mid = call_intrinsic + extrinsic
            put_mid = put_intrinsic + extrinsic

            contracts.append(
                OptionContract(
                    ticker=ticker,
                    contract_type="CALL",
                    strike=strike,
                    expiration=expiration,
                    bid=round(max(0.01, call_mid * 0.97), 4),
                    ask=round(max(0.02, call_mid * 1.03), 4),
                    last=round(call_mid, 4),
                    volume=liquidity,
                    open_interest=liquidity * 2,
                    implied_volatility=hist_vol,
                    delta=None,
                )
            )
            contracts.append(
                OptionContract(
                    ticker=ticker,
                    contract_type="PUT",
                    strike=strike,
                    expiration=expiration,
                    bid=round(max(0.01, put_mid * 0.97), 4),
                    ask=round(max(0.02, put_mid * 1.03), 4),
                    last=round(put_mid, 4),
                    volume=liquidity,
                    open_interest=liquidity * 2,
                    implied_volatility=hist_vol,
                    delta=None,
                )
            )

    return contracts


def get_options_chain_for_ticker(
    ticker: str,
    scraper: YahooFinanceOptionsScraper,
    max_expirations: int = 2,
    force_refresh: bool = False,
) -> tuple[list[OptionContract], str]:
    ticker = ticker.upper()
    rows = db.get_option_chain(ticker)
    cached_contracts = _rows_to_contracts(rows)
    last_updated = _parse_dt(db.get_option_chain_last_updated(ticker))
    cached_source = db.get_option_chain_source(ticker) or "unknown"
    trusted_cached = cached_source != "unknown"

    cache_fresh = False
    if last_updated is not None:
        age = datetime.now() - last_updated
        cache_fresh = age <= timedelta(minutes=OPTIONS_CACHE_MAX_AGE_MINUTES)

    if not force_refresh and cached_contracts and cache_fresh and trusted_cached:
        return cached_contracts, f"cache:{cached_source}"

    try:
        chain = scraper.get_all_expirations(ticker, max_expirations=max_expirations, include_puts=True)
        contracts = [contract for bucket in chain.values() for contract in bucket]
        if contracts:
            db.upsert_option_chain(ticker, contracts, source="nasdaq")
            return contracts, "live:nasdaq"
    except Exception:
        if cached_contracts and trusted_cached:
            return cached_contracts, f"stale_cache:{cached_source}"
        if OPTIONS_ALLOW_SYNTHETIC_FALLBACK:
            synthetic = _build_synthetic_chain(ticker)
            if synthetic:
                db.upsert_option_chain(ticker, synthetic, source="synthetic")
                return synthetic, "live:synthetic_estimated"
        raise

    if cached_contracts and trusted_cached:
        return cached_contracts, f"stale_cache:{cached_source}"
    if OPTIONS_ALLOW_SYNTHETIC_FALLBACK:
        synthetic = _build_synthetic_chain(ticker)
        if synthetic:
            db.upsert_option_chain(ticker, synthetic, source="synthetic")
            return synthetic, "live:synthetic_estimated"
    return [], "empty"
