from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from strategy_ml.types import StrategyClass


@dataclass(frozen=True)
class StrategyPayoffConfig:
    dte_days: int = 10
    spread_width_pct: float = 0.05
    min_premium_pct: float = 0.006


class StrategyBacktester:
    """
    Simplified options strategy simulator for label optimization and model evaluation.

    This engine uses underlying move + volatility proxy assumptions and is intentionally
    deterministic so the same training set is reproducible.
    """

    def __init__(self, config: StrategyPayoffConfig = StrategyPayoffConfig()):
        self.config = config

    def simulate_return(
        self,
        strategy: StrategyClass,
        feature_row: pd.Series,
        future_prices: pd.Series,
    ) -> float:
        if future_prices.empty or np.isnan(feature_row.get("close", np.nan)):
            return 0.0

        entry = float(feature_row["close"])
        exit_price = float(future_prices.iloc[-1])
        move = (exit_price - entry) / max(entry, 1e-6)

        future_rets = np.log(future_prices).diff().dropna()
        realized_vol = float(future_rets.std() * np.sqrt(252)) if not future_rets.empty else 0.0
        hist_vol = float(feature_row.get("hist_vol_20", 0.25) or 0.25)
        vol_proxy = max(0.05, min(1.2, 0.6 * hist_vol + 0.4 * realized_vol))

        dte = self.config.dte_days
        expected_move_pct = vol_proxy * np.sqrt(dte / 252)
        spread_width = self.config.spread_width_pct

        # Premium approximation calibrated to expected move and volatility.
        call_premium = max(self.config.min_premium_pct, expected_move_pct * 0.40)
        put_premium = max(self.config.min_premium_pct, expected_move_pct * 0.40)
        straddle_cost = max(self.config.min_premium_pct * 2, expected_move_pct * 0.90)

        if strategy == StrategyClass.BULL_CALL_SPREAD:
            gross = min(max(move, 0.0), spread_width)
            debit = call_premium * 0.75
            return gross - debit

        if strategy == StrategyClass.BEAR_PUT_SPREAD:
            gross = min(max(-move, 0.0), spread_width)
            debit = put_premium * 0.75
            return gross - debit

        if strategy == StrategyClass.IRON_CONDOR:
            credit = call_premium + put_premium
            safe_band = expected_move_pct * 0.85
            if abs(move) <= safe_band:
                return credit
            overflow = min(spread_width, max(0.0, abs(move) - safe_band))
            return credit - overflow

        if strategy == StrategyClass.LONG_STRADDLE:
            return abs(move) - straddle_cost

        return 0.0

    def relabel_best_strategy(
        self,
        features: pd.DataFrame,
        horizon_bars: int = 10,
    ) -> pd.Series:
        labels: list[str] = []
        closes = features["close"].reset_index(drop=True)

        candidate_strategies = [
            StrategyClass.BULL_CALL_SPREAD,
            StrategyClass.BEAR_PUT_SPREAD,
            StrategyClass.IRON_CONDOR,
            StrategyClass.LONG_STRADDLE,
            StrategyClass.NO_TRADE,
        ]

        for idx in range(len(features)):
            future_window = closes.iloc[idx + 1 : idx + 1 + horizon_bars]
            if len(future_window) < horizon_bars:
                labels.append(StrategyClass.NO_TRADE.value)
                continue

            row = features.iloc[idx]
            perf = {
                s.value: self.simulate_return(s, row, future_window)
                for s in candidate_strategies
            }
            best = max(perf.items(), key=lambda x: x[1])[0]
            labels.append(best if perf[best] > 0 else StrategyClass.NO_TRADE.value)

        return pd.Series(labels, index=features.index, name="strategy_label")

    def evaluate_predicted_signals(
        self,
        features: pd.DataFrame,
        predicted_labels: pd.Series,
        horizon_bars: int = 10,
    ) -> dict:
        closes = features["close"].reset_index(drop=True)
        pnl = []

        for idx, label in enumerate(predicted_labels.tolist()):
            strategy = StrategyClass(label)
            future_window = closes.iloc[idx + 1 : idx + 1 + horizon_bars]
            if len(future_window) < horizon_bars:
                continue
            trade_ret = self.simulate_return(strategy, features.iloc[idx], future_window)
            if strategy != StrategyClass.NO_TRADE:
                pnl.append(trade_ret)

        if not pnl:
            return {"total_return": 0.0, "win_rate": 0.0, "avg_return_per_trade": 0.0, "trades": 0}

        pnl_arr = np.array(pnl)
        return {
            "total_return": float(pnl_arr.sum()),
            "win_rate": float((pnl_arr > 0).mean()),
            "avg_return_per_trade": float(pnl_arr.mean()),
            "trades": int(len(pnl)),
        }
