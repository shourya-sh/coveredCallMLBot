from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from ml.features import build_features
from ml.types import FEATURE_COLUMNS, StrategyClass

ARTIFACT_PATH = Path(__file__).parent / "artifacts" / "options_strategy_model.joblib"


def _load_candles(ticker: str, limit: int = 600) -> pd.DataFrame:
    import db
    rows = db.load_candles(ticker, limit=limit)
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["datetime"] = pd.to_datetime(df["datetime"], utc=True)
    return df


# ── Execution plan helpers ────────────────────────────────────────────────────

def _nearest_friday_contracts(contracts: list) -> list:
    if not contracts:
        return []
    now = datetime.now()
    expirations = sorted({c.expiration for c in contracts if c.expiration >= now})
    if not expirations:
        expirations = sorted({c.expiration for c in contracts})
    if not expirations:
        return []
    days_until_friday = (4 - now.weekday()) % 7 or 7
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


def _payoff_curve(strategy: StrategyClass, spot: float, *, k1, k2=None, k3=None, k4=None, net_premium=0.0) -> list[dict]:
    if spot <= 0:
        return []
    points = []
    for i in range(41):
        s = spot * 0.7 + (spot * 0.6 * i / 40)
        pnl = 0.0
        if strategy == StrategyClass.BULL_CALL_SPREAD and k2:
            pnl = max(s - k1, 0) - max(s - k2, 0) + net_premium
        elif strategy == StrategyClass.BEAR_PUT_SPREAD and k2:
            pnl = max(k1 - s, 0) - max(k2 - s, 0) + net_premium
        elif strategy == StrategyClass.IRON_CONDOR and k2 and k3 and k4:
            pnl = net_premium - (max(k3 - s, 0) - max(k4 - s, 0)) - (max(s - k1, 0) - max(s - k2, 0))
        elif strategy == StrategyClass.LONG_STRADDLE:
            pnl = max(s - k1, 0) + max(k1 - s, 0) + net_premium
        points.append({"price": round(s, 2), "pnl": round(pnl * 100, 2)})
    return points


def _build_execution_plan(strategy: StrategyClass, contracts: list, spot: float) -> dict | None:
    if strategy == StrategyClass.NO_TRADE or not contracts:
        return None

    nearest = _nearest_friday_contracts(contracts)
    calls = sorted([c for c in nearest if c.contract_type == "CALL"], key=lambda c: c.strike)
    puts = sorted([c for c in nearest if c.contract_type == "PUT"], key=lambda c: c.strike)

    if strategy == StrategyClass.BULL_CALL_SPREAD and calls:
        lc = min(calls, key=lambda c: abs(c.strike - spot))
        sc_candidates = [c for c in calls if c.strike > lc.strike]
        sc = sc_candidates[0] if sc_candidates else lc
        net_debit = max(0.0, lc.mid_price - sc.mid_price)
        width = max(0.0, sc.strike - lc.strike)
        return {
            "strategy": strategy.value,
            "expiration": lc.expiration.strftime("%Y-%m-%d"),
            "expiry_meta": _expiry_meta(lc.expiration),
            "legs": [
                {"side": "BUY", "type": "CALL", "strike": lc.strike, "bid": round(lc.bid, 4), "ask": round(lc.ask, 4), "mid": round(lc.mid_price, 4)},
                {"side": "SELL", "type": "CALL", "strike": sc.strike, "bid": round(sc.bid, 4), "ask": round(sc.ask, 4), "mid": round(sc.mid_price, 4)},
            ],
            "summary": {
                "net_premium": round(-net_debit * 100, 2),
                "max_profit": round(max(0.0, width - net_debit) * 100, 2),
                "max_loss": round(net_debit * 100, 2),
                "break_even": round(lc.strike + net_debit, 2),
            },
            "payoff_curve": _payoff_curve(strategy, spot, k1=lc.strike, k2=sc.strike, net_premium=-net_debit),
        }

    if strategy == StrategyClass.BEAR_PUT_SPREAD and puts:
        lp = min(puts, key=lambda p: abs(p.strike - spot))
        sp_candidates = [p for p in reversed(puts) if p.strike < lp.strike]
        sp = sp_candidates[0] if sp_candidates else lp
        net_debit = max(0.0, lp.mid_price - sp.mid_price)
        width = max(0.0, lp.strike - sp.strike)
        return {
            "strategy": strategy.value,
            "expiration": lp.expiration.strftime("%Y-%m-%d"),
            "expiry_meta": _expiry_meta(lp.expiration),
            "legs": [
                {"side": "BUY", "type": "PUT", "strike": lp.strike, "bid": round(lp.bid, 4), "ask": round(lp.ask, 4), "mid": round(lp.mid_price, 4)},
                {"side": "SELL", "type": "PUT", "strike": sp.strike, "bid": round(sp.bid, 4), "ask": round(sp.ask, 4), "mid": round(sp.mid_price, 4)},
            ],
            "summary": {
                "net_premium": round(-net_debit * 100, 2),
                "max_profit": round(max(0.0, width - net_debit) * 100, 2),
                "max_loss": round(net_debit * 100, 2),
                "break_even": round(lp.strike - net_debit, 2),
            },
            "payoff_curve": _payoff_curve(strategy, spot, k1=lp.strike, k2=sp.strike, net_premium=-net_debit),
        }

    if strategy == StrategyClass.IRON_CONDOR and calls and puts:
        sc = min([c for c in calls if c.strike >= spot] or calls, key=lambda c: abs(c.strike - spot))
        lc = next((c for c in calls if c.strike > sc.strike), sc)
        sp = min([p for p in puts if p.strike <= spot] or puts, key=lambda p: abs(p.strike - spot))
        lp = next((p for p in reversed(puts) if p.strike < sp.strike), sp)
        net_credit = (sc.mid_price + sp.mid_price) - (lc.mid_price + lp.mid_price)
        width = max(max(0.0, lc.strike - sc.strike), max(0.0, sp.strike - lp.strike))
        return {
            "strategy": strategy.value,
            "expiration": sc.expiration.strftime("%Y-%m-%d"),
            "expiry_meta": _expiry_meta(sc.expiration),
            "legs": [
                {"side": "SELL", "type": "CALL", "strike": sc.strike, "bid": round(sc.bid, 4), "ask": round(sc.ask, 4), "mid": round(sc.mid_price, 4)},
                {"side": "BUY", "type": "CALL", "strike": lc.strike, "bid": round(lc.bid, 4), "ask": round(lc.ask, 4), "mid": round(lc.mid_price, 4)},
                {"side": "SELL", "type": "PUT", "strike": sp.strike, "bid": round(sp.bid, 4), "ask": round(sp.ask, 4), "mid": round(sp.mid_price, 4)},
                {"side": "BUY", "type": "PUT", "strike": lp.strike, "bid": round(lp.bid, 4), "ask": round(lp.ask, 4), "mid": round(lp.mid_price, 4)},
            ],
            "summary": {
                "net_premium": round(net_credit * 100, 2),
                "max_profit": round(max(0.0, net_credit) * 100, 2),
                "max_loss": round(max(0.0, width - net_credit) * 100, 2),
                "break_even_lower": round(sp.strike - max(0.0, net_credit), 2),
                "break_even_upper": round(sc.strike + max(0.0, net_credit), 2),
            },
            "payoff_curve": _payoff_curve(strategy, spot, k1=sc.strike, k2=lc.strike, k3=sp.strike, k4=lp.strike, net_premium=net_credit),
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
                "net_premium": round(-net_debit * 100, 2),
                "max_profit": None,
                "max_loss": round(net_debit * 100, 2),
                "break_even_lower": round(call.strike - net_debit, 2),
                "break_even_upper": round(call.strike + net_debit, 2),
            },
            "payoff_curve": _payoff_curve(strategy, spot, k1=call.strike, net_premium=-net_debit),
        }

    return None


# ── Predictor ─────────────────────────────────────────────────────────────────

class StrategyPredictor:
    def __init__(self, model_path: str = "", confidence_threshold: float = 0.33, volatility_ceiling: float = 1.0):
        model_path = model_path or str(ARTIFACT_PATH)
        print(f"[model] Loading from {model_path}...")
        artifact = joblib.load(model_path)
        self.pipeline = artifact["pipeline"]
        self.label_encoder = artifact["label_encoder"]
        self.feature_columns = artifact["feature_columns"]
        self.confidence_threshold = confidence_threshold
        self.volatility_ceiling = volatility_ceiling
        print(f"[model] Loaded — classes: {list(self.label_encoder.classes_)}")

    def predict(self, ticker: str, contracts: list | None = None) -> dict:
        ticker = ticker.upper()
        candles = _load_candles(ticker)
        spy = _load_candles("SPY")

        if candles.empty:
            return _no_trade(ticker, "no_candles")

        features = build_features(candles, spy_candles=spy).replace([np.inf, -np.inf], np.nan)
        latest = features.iloc[-1:]

        probs_arr = self.pipeline.predict_proba(latest[self.feature_columns])[0]
        labels = self.label_encoder.inverse_transform(np.arange(len(probs_arr)))
        probs = {label: float(p) for label, p in zip(labels, probs_arr)}

        top_strategy, confidence = max(probs.items(), key=lambda x: x[1])
        risk_flags = []

        if confidence < self.confidence_threshold:
            top_strategy = StrategyClass.NO_TRADE.value
            risk_flags.append("low_confidence")

        latest_vol = float(latest["hist_vol_20"].iloc[0]) if not latest["hist_vol_20"].isna().iloc[0] else np.nan
        if not np.isnan(latest_vol) and latest_vol > self.volatility_ceiling:
            top_strategy = StrategyClass.NO_TRADE.value
            risk_flags.append("extreme_volatility")

        spot = float(latest["close"].iloc[0])
        liquidity_score = int(sum(c.open_interest + c.volume for c in contracts)) if contracts else 0

        if contracts and liquidity_score < 100:
            top_strategy = StrategyClass.NO_TRADE.value
            risk_flags.append("low_liquidity")

        execution_plan = _build_execution_plan(StrategyClass(top_strategy), contracts or [], spot)

        return {
            "ticker": ticker,
            "top_strategy": top_strategy,
            "confidence": round(confidence, 4),
            "probabilities": {k: round(v, 4) for k, v in sorted(probs.items(), key=lambda x: -x[1])},
            "risk_flags": risk_flags,
            "liquidity_score": liquidity_score,
            "spot": spot,
            "execution_plan": execution_plan,
        }


def _no_trade(ticker: str, flag: str) -> dict:
    return {
        "ticker": ticker,
        "top_strategy": StrategyClass.NO_TRADE.value,
        "confidence": 0.0,
        "probabilities": {StrategyClass.NO_TRADE.value: 1.0},
        "risk_flags": [flag],
        "liquidity_score": 0,
        "spot": 0.0,
        "execution_plan": None,
    }
