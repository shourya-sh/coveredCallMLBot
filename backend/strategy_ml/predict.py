from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from data_ingestion.options_scraper import OptionContract, YahooFinanceOptionsScraper, get_options_scraper
from strategy_ml.data_loader import CandleDataLoader
from strategy_ml.feature_engineering import build_feature_frame
from strategy_ml.types import StrategyClass


def _nearest_expiration_contracts(contracts: list[OptionContract]) -> list[OptionContract]:
    if not contracts:
        return []
    now = datetime.now()
    expirations = sorted({c.expiration for c in contracts if c.expiration >= now})
    if not expirations:
        expirations = sorted({c.expiration for c in contracts})
    if not expirations:
        return []

    # Prefer the nearest Friday expiration at/after the next Friday.
    days_until_friday = (4 - now.weekday()) % 7
    if days_until_friday == 0:
        days_until_friday = 7
    target_friday = (now + timedelta(days=days_until_friday)).date()
    friday_candidates = [e for e in expirations if e.weekday() == 4 and e.date() >= target_friday]
    chosen = friday_candidates[0] if friday_candidates else expirations[0]
    return [c for c in contracts if c.expiration == chosen]


def _expiry_meta(expiration: datetime) -> dict:
    dte = max(0, (expiration.date() - datetime.now().date()).days)
    if dte == 0:
        signal = "Expires today"
    elif dte == 1:
        signal = "Expires tomorrow"
    elif dte <= 3:
        signal = f"Expires in {dte} days"
    elif expiration.weekday() == 4 and dte <= 7:
        signal = "Expires this Friday"
    else:
        signal = f"Expires in {dte} days"

    return {"date": expiration.strftime("%Y-%m-%d"), "days_to_expiration": dte, "signal": signal}


def _build_payoff_curve(
    strategy: StrategyClass,
    spot: float,
    *,
    k1: float,
    k2: float | None = None,
    k3: float | None = None,
    k4: float | None = None,
    net_premium_per_share: float = 0.0,
) -> list[dict]:
    if spot <= 0:
        return []

    points = []
    lo = spot * 0.7
    hi = spot * 1.3
    steps = 40
    for i in range(steps + 1):
        s = lo + ((hi - lo) * i / steps)
        pnl = 0.0

        if strategy == StrategyClass.BULL_CALL_SPREAD and k2 is not None:
            pnl = max(s - k1, 0.0) - max(s - k2, 0.0) + net_premium_per_share
        elif strategy == StrategyClass.BEAR_PUT_SPREAD and k2 is not None:
            pnl = max(k1 - s, 0.0) - max(k2 - s, 0.0) + net_premium_per_share
        elif strategy == StrategyClass.IRON_CONDOR and k2 is not None and k3 is not None and k4 is not None:
            put_loss = max(k3 - s, 0.0) - max(k4 - s, 0.0)
            call_loss = max(s - k1, 0.0) - max(s - k2, 0.0)
            pnl = net_premium_per_share - put_loss - call_loss
        elif strategy == StrategyClass.LONG_STRADDLE:
            pnl = max(s - k1, 0.0) + max(k1 - s, 0.0) + net_premium_per_share

        points.append({"price": round(s, 2), "pnl": round(pnl * 100, 2)})

    return points


def _build_execution_plan(
    strategy: StrategyClass,
    contracts: list[OptionContract],
    spot: float,
) -> dict | None:
    if strategy == StrategyClass.NO_TRADE or not contracts:
        return None

    nearest = _nearest_expiration_contracts(contracts)
    calls = sorted([c for c in nearest if c.contract_type == "CALL"], key=lambda c: c.strike)
    puts = sorted([p for p in nearest if p.contract_type == "PUT"], key=lambda p: p.strike)

    if strategy == StrategyClass.BULL_CALL_SPREAD and calls:
        long_call = min(calls, key=lambda c: abs(c.strike - spot))
        short_candidates = [c for c in calls if c.strike > long_call.strike]
        short_call = short_candidates[0] if short_candidates else long_call
        net_debit = max(0.0, long_call.mid_price - short_call.mid_price)
        width = max(0.0, short_call.strike - long_call.strike)
        max_profit = max(0.0, width - net_debit)
        max_loss = net_debit
        return {
            "strategy": strategy.value,
            "expiration": long_call.expiration.strftime("%Y-%m-%d"),
            "expiry_meta": _expiry_meta(long_call.expiration),
            "legs": [
                {"side": "BUY", "type": "CALL", "strike": long_call.strike, "bid": round(long_call.bid, 4), "ask": round(long_call.ask, 4), "mid": round(long_call.mid_price, 4)},
                {"side": "SELL", "type": "CALL", "strike": short_call.strike, "bid": round(short_call.bid, 4), "ask": round(short_call.ask, 4), "mid": round(short_call.mid_price, 4)},
            ],
            "summary": {
                "upfront_credit": 0.0,
                "net_premium": round(-net_debit * 100, 2),
                "max_profit": round(max_profit * 100, 2),
                "max_loss": round(max_loss * 100, 2),
                "break_even_lower": round(long_call.strike + net_debit, 2),
                "break_even_upper": None,
            },
            "payoff_curve": _build_payoff_curve(
                strategy,
                spot,
                k1=long_call.strike,
                k2=short_call.strike,
                net_premium_per_share=-net_debit,
            ),
        }

    if strategy == StrategyClass.BEAR_PUT_SPREAD and puts:
        long_put = min(puts, key=lambda p: abs(p.strike - spot))
        short_candidates = [p for p in reversed(puts) if p.strike < long_put.strike]
        short_put = short_candidates[0] if short_candidates else long_put
        net_debit = max(0.0, long_put.mid_price - short_put.mid_price)
        width = max(0.0, long_put.strike - short_put.strike)
        max_profit = max(0.0, width - net_debit)
        max_loss = net_debit
        return {
            "strategy": strategy.value,
            "expiration": long_put.expiration.strftime("%Y-%m-%d"),
            "expiry_meta": _expiry_meta(long_put.expiration),
            "legs": [
                {"side": "BUY", "type": "PUT", "strike": long_put.strike, "bid": round(long_put.bid, 4), "ask": round(long_put.ask, 4), "mid": round(long_put.mid_price, 4)},
                {"side": "SELL", "type": "PUT", "strike": short_put.strike, "bid": round(short_put.bid, 4), "ask": round(short_put.ask, 4), "mid": round(short_put.mid_price, 4)},
            ],
            "summary": {
                "upfront_credit": 0.0,
                "net_premium": round(-net_debit * 100, 2),
                "max_profit": round(max_profit * 100, 2),
                "max_loss": round(max_loss * 100, 2),
                "break_even_lower": round(long_put.strike - net_debit, 2),
                "break_even_upper": None,
            },
            "payoff_curve": _build_payoff_curve(
                strategy,
                spot,
                k1=long_put.strike,
                k2=short_put.strike,
                net_premium_per_share=-net_debit,
            ),
        }

    if strategy == StrategyClass.IRON_CONDOR and calls and puts:
        short_call = min([c for c in calls if c.strike >= spot] or calls, key=lambda c: abs(c.strike - spot))
        long_call = next((c for c in calls if c.strike > short_call.strike), short_call)
        short_put = min([p for p in puts if p.strike <= spot] or puts, key=lambda p: abs(p.strike - spot))
        long_put = next((p for p in reversed(puts) if p.strike < short_put.strike), short_put)
        net_credit = (short_call.mid_price + short_put.mid_price) - (long_call.mid_price + long_put.mid_price)
        call_width = max(0.0, long_call.strike - short_call.strike)
        put_width = max(0.0, short_put.strike - long_put.strike)
        width = max(call_width, put_width)
        max_profit = max(0.0, net_credit)
        max_loss = max(0.0, width - net_credit)
        return {
            "strategy": strategy.value,
            "expiration": short_call.expiration.strftime("%Y-%m-%d"),
            "expiry_meta": _expiry_meta(short_call.expiration),
            "legs": [
                {"side": "SELL", "type": "CALL", "strike": short_call.strike, "bid": round(short_call.bid, 4), "ask": round(short_call.ask, 4), "mid": round(short_call.mid_price, 4)},
                {"side": "BUY", "type": "CALL", "strike": long_call.strike, "bid": round(long_call.bid, 4), "ask": round(long_call.ask, 4), "mid": round(long_call.mid_price, 4)},
                {"side": "SELL", "type": "PUT", "strike": short_put.strike, "bid": round(short_put.bid, 4), "ask": round(short_put.ask, 4), "mid": round(short_put.mid_price, 4)},
                {"side": "BUY", "type": "PUT", "strike": long_put.strike, "bid": round(long_put.bid, 4), "ask": round(long_put.ask, 4), "mid": round(long_put.mid_price, 4)},
            ],
            "summary": {
                "upfront_credit": round(max(0.0, net_credit) * 100, 2),
                "net_premium": round(net_credit * 100, 2),
                "max_profit": round(max_profit * 100, 2),
                "max_loss": round(max_loss * 100, 2),
                "break_even_lower": round(short_put.strike - max(0.0, net_credit), 2),
                "break_even_upper": round(short_call.strike + max(0.0, net_credit), 2),
            },
            "payoff_curve": _build_payoff_curve(
                strategy,
                spot,
                k1=short_call.strike,
                k2=long_call.strike,
                k3=short_put.strike,
                k4=long_put.strike,
                net_premium_per_share=net_credit,
            ),
        }

    if strategy == StrategyClass.LONG_STRADDLE and calls and puts:
        call = min(calls, key=lambda c: abs(c.strike - spot))
        put = min(puts, key=lambda p: abs(p.strike - spot))
        net_debit = call.mid_price + put.mid_price
        return {
            "strategy": strategy.value,
            "expiration": call.expiration.strftime("%Y-%m-%d"),
            "expiry_meta": _expiry_meta(call.expiration),
            "legs": [
                {"side": "BUY", "type": "CALL", "strike": call.strike, "bid": round(call.bid, 4), "ask": round(call.ask, 4), "mid": round(call.mid_price, 4)},
                {"side": "BUY", "type": "PUT", "strike": put.strike, "bid": round(put.bid, 4), "ask": round(put.ask, 4), "mid": round(put.mid_price, 4)},
            ],
            "summary": {
                "upfront_credit": 0.0,
                "net_premium": round(-net_debit * 100, 2),
                "max_profit": None,
                "max_loss": round(net_debit * 100, 2),
                "break_even_lower": round(call.strike - net_debit, 2),
                "break_even_upper": round(call.strike + net_debit, 2),
            },
            "payoff_curve": _build_payoff_curve(
                strategy,
                spot,
                k1=call.strike,
                net_premium_per_share=-net_debit,
            ),
        }

    return None


def _build_strategy_setups(
    probs: dict[str, float],
    contracts: list[OptionContract],
    spot: float,
) -> list[dict]:
    setups: list[dict] = []
    ordered = sorted(probs.items(), key=lambda x: -x[1])

    for label, prob in ordered:
        if label == StrategyClass.NO_TRADE.value:
            continue
        plan = _build_execution_plan(StrategyClass(label), contracts, spot) if contracts else None
        setups.append(
            {
                "strategy": label,
                "confidence": round(float(prob), 4),
                "execution_plan": plan,
            }
        )

    return setups


class StrategyPredictor:
    def __init__(
        self,
        model_path: str = "",
        confidence_threshold: float = 0.33,
        volatility_ceiling: float = 1.00,
        min_oi_plus_volume: int = 100,
        options_scraper: YahooFinanceOptionsScraper | None = None,
    ):
        if not model_path:
            model_path = str(Path(__file__).resolve().parent / "artifacts" / "options_strategy_model.joblib")
        artifact = joblib.load(model_path)
        self.pipeline = artifact["pipeline"]
        self.label_encoder = artifact["label_encoder"]
        self.feature_columns = artifact["feature_columns"]
        self.loader = CandleDataLoader()
        self.options_scraper = options_scraper or get_options_scraper()
        self.confidence_threshold = confidence_threshold
        self.volatility_ceiling = volatility_ceiling
        self.min_oi_plus_volume = min_oi_plus_volume

    def predict_ticker(self, ticker: str, interval: str = "1day", limit: int = 400) -> dict:
        return self._predict_ticker_impl(ticker=ticker, interval=interval, limit=limit, include_execution_plan=False)

    def predict_ticker_with_execution_plan(
        self,
        ticker: str,
        interval: str = "1day",
        limit: int = 400,
        contracts_override: list[OptionContract] | None = None,
    ) -> dict:
        return self._predict_ticker_impl(
            ticker=ticker,
            interval=interval,
            limit=limit,
            include_execution_plan=True,
            contracts_override=contracts_override,
        )

    def _predict_ticker_impl(
        self,
        ticker: str,
        interval: str = "1day",
        limit: int = 400,
        include_execution_plan: bool = False,
        contracts_override: list[OptionContract] | None = None,
    ) -> dict:
        ticker = ticker.upper()
        candles = self.loader.load_candles(ticker, interval=interval, limit=limit)
        spy = self.loader.load_candles("SPY", interval=interval, limit=limit)
        if candles.empty:
            return {
                "ticker": ticker,
                "top_strategy": StrategyClass.NO_TRADE.value,
                "confidence": 0.0,
                "probabilities": {StrategyClass.NO_TRADE.value: 1.0},
                "risk_flags": ["no_candles"],
                "liquidity_score": 0,
                "execution_plan": None,
                "reason": "No candles available",
            }

        features = build_feature_frame(candles, spy_candles=spy)
        features = features.replace([np.inf, -np.inf], np.nan)
        latest = features.iloc[-1:]

        probs_arr = self.pipeline.predict_proba(latest[self.feature_columns])[0]
        labels = self.label_encoder.inverse_transform(np.arange(len(probs_arr)))
        probs = {label: float(prob) for label, prob in zip(labels, probs_arr)}

        raw_top_strategy = max(probs.items(), key=lambda x: x[1])[0]
        top_strategy = raw_top_strategy
        confidence = probs[top_strategy]

        risk_flags = []
        if confidence < self.confidence_threshold:
            top_strategy = StrategyClass.NO_TRADE.value
            risk_flags.append("confidence_below_threshold")

        latest_vol = float(latest["hist_vol_20"].iloc[0]) if not latest["hist_vol_20"].isna().iloc[0] else np.nan
        if not np.isnan(latest_vol) and latest_vol > self.volatility_ceiling:
            top_strategy = StrategyClass.NO_TRADE.value
            risk_flags.append("volatility_too_extreme")

        contracts = []
        liquidity_score = 0
        if include_execution_plan:
            if contracts_override is not None:
                contracts = contracts_override
            else:
                try:
                    chain = self.options_scraper.get_all_expirations(ticker, max_expirations=2, include_puts=True)
                    contracts = [contract for bucket in chain.values() for contract in bucket]
                except Exception:
                    # Keep model recommendation even if live chain is temporarily unavailable.
                    risk_flags.append("options_unavailable")

            liquidity_score = int(sum(c.open_interest + c.volume for c in contracts)) if contracts else 0
            if contracts and liquidity_score < self.min_oi_plus_volume:
                top_strategy = StrategyClass.NO_TRADE.value
                risk_flags.append("low_liquidity")

        spot = float(latest["close"].iloc[0])
        execution_strategy = top_strategy
        if include_execution_plan and execution_strategy == StrategyClass.NO_TRADE.value and contracts and raw_top_strategy != StrategyClass.NO_TRADE.value:
            execution_strategy = raw_top_strategy
            risk_flags.append("setup_from_low_confidence_signal")

        execution_plan = _build_execution_plan(StrategyClass(execution_strategy), contracts, spot) if include_execution_plan else None
        strategy_setups = _build_strategy_setups(probs, contracts, spot) if include_execution_plan else []

        return {
            "ticker": ticker,
            "top_strategy": top_strategy,
            "confidence": round(confidence, 4),
            "probabilities": {k: round(v, 4) for k, v in sorted(probs.items(), key=lambda x: -x[1])},
            "risk_flags": risk_flags,
            "liquidity_score": liquidity_score,
            "execution_plan": execution_plan,
            "setup_strategy": execution_strategy if include_execution_plan else None,
            "strategy_setups": strategy_setups,
        }

    def predict_universe(self, tickers: list[str], interval: str = "1day", limit: int = 400) -> list[dict]:
        return [self.predict_ticker(t, interval=interval, limit=limit) for t in tickers]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run options strategy prediction")
    parser.add_argument("--ticker", default="AAPL")
    parser.add_argument("--model", default=str(Path(__file__).resolve().parent / "artifacts" / "options_strategy_model.joblib"))
    parser.add_argument("--interval", default="1day")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    predictor = StrategyPredictor(model_path=args.model)
    result = predictor.predict_ticker(args.ticker, interval=args.interval)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
