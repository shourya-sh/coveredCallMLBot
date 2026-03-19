from __future__ import annotations

import argparse
import json
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
    nearest = min(c.expiration for c in contracts)
    return [c for c in contracts if c.expiration == nearest]


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
            "legs": [
                {"side": "BUY", "type": "CALL", "strike": long_call.strike, "mid": round(long_call.mid_price, 4)},
                {"side": "SELL", "type": "CALL", "strike": short_call.strike, "mid": round(short_call.mid_price, 4)},
            ],
            "summary": {
                "upfront_credit": 0.0,
                "net_premium": round(-net_debit * 100, 2),
                "max_profit": round(max_profit * 100, 2),
                "max_loss": round(max_loss * 100, 2),
            },
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
            "legs": [
                {"side": "BUY", "type": "PUT", "strike": long_put.strike, "mid": round(long_put.mid_price, 4)},
                {"side": "SELL", "type": "PUT", "strike": short_put.strike, "mid": round(short_put.mid_price, 4)},
            ],
            "summary": {
                "upfront_credit": 0.0,
                "net_premium": round(-net_debit * 100, 2),
                "max_profit": round(max_profit * 100, 2),
                "max_loss": round(max_loss * 100, 2),
            },
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
            "legs": [
                {"side": "SELL", "type": "CALL", "strike": short_call.strike, "mid": round(short_call.mid_price, 4)},
                {"side": "BUY", "type": "CALL", "strike": long_call.strike, "mid": round(long_call.mid_price, 4)},
                {"side": "SELL", "type": "PUT", "strike": short_put.strike, "mid": round(short_put.mid_price, 4)},
                {"side": "BUY", "type": "PUT", "strike": long_put.strike, "mid": round(long_put.mid_price, 4)},
            ],
            "summary": {
                "upfront_credit": round(max(0.0, net_credit) * 100, 2),
                "net_premium": round(net_credit * 100, 2),
                "max_profit": round(max_profit * 100, 2),
                "max_loss": round(max_loss * 100, 2),
            },
        }

    if strategy == StrategyClass.LONG_STRADDLE and calls and puts:
        call = min(calls, key=lambda c: abs(c.strike - spot))
        put = min(puts, key=lambda p: abs(p.strike - spot))
        net_debit = call.mid_price + put.mid_price
        return {
            "strategy": strategy.value,
            "expiration": call.expiration.strftime("%Y-%m-%d"),
            "legs": [
                {"side": "BUY", "type": "CALL", "strike": call.strike, "mid": round(call.mid_price, 4)},
                {"side": "BUY", "type": "PUT", "strike": put.strike, "mid": round(put.mid_price, 4)},
            ],
            "summary": {
                "upfront_credit": 0.0,
                "net_premium": round(-net_debit * 100, 2),
                "max_profit": None,
                "max_loss": round(net_debit * 100, 2),
            },
        }

    return None


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

        top_strategy = max(probs.items(), key=lambda x: x[1])[0]
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
        execution_plan = _build_execution_plan(StrategyClass(top_strategy), contracts, spot) if include_execution_plan else None

        return {
            "ticker": ticker,
            "top_strategy": top_strategy,
            "confidence": round(confidence, 4),
            "probabilities": {k: round(v, 4) for k, v in sorted(probs.items(), key=lambda x: -x[1])},
            "risk_flags": risk_flags,
            "liquidity_score": liquidity_score,
            "execution_plan": execution_plan,
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
