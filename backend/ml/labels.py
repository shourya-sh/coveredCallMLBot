from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from ml.types import StrategyClass


@dataclass(frozen=True)
class BacktestConfig:
    dte_days: int = 10
    spread_width_pct: float = 0.05
    min_premium_pct: float = 0.006


def simulate_return(
    strategy: StrategyClass,
    feature_row: pd.Series,
    future_prices: pd.Series,
    config: BacktestConfig = BacktestConfig(),
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

    expected_move = vol_proxy * np.sqrt(config.dte_days / 252)
    width = config.spread_width_pct
    call_premium = max(config.min_premium_pct, expected_move * 0.40)
    put_premium = max(config.min_premium_pct, expected_move * 0.40)
    straddle_cost = max(config.min_premium_pct * 2, expected_move * 0.90)

    if strategy == StrategyClass.BULL_CALL_SPREAD:
        return min(max(move, 0.0), width) - call_premium * 0.75

    if strategy == StrategyClass.BEAR_PUT_SPREAD:
        return min(max(-move, 0.0), width) - put_premium * 0.75

    if strategy == StrategyClass.IRON_CONDOR:
        credit = call_premium + put_premium
        safe_band = expected_move * 0.85
        if abs(move) <= safe_band:
            return credit
        overflow = min(width, max(0.0, abs(move) - safe_band))
        return credit - overflow

    if strategy == StrategyClass.LONG_STRADDLE:
        return abs(move) - straddle_cost

    return 0.0


def generate_labels(features: pd.DataFrame, horizon_bars: int = 10) -> pd.Series:
    """
    For each bar, simulate all strategies over the next `horizon_bars` days.
    Label = strategy with highest positive return, or NO_TRADE if none profitable.
    """
    candidates = [
        StrategyClass.BULL_CALL_SPREAD,
        StrategyClass.BEAR_PUT_SPREAD,
        StrategyClass.IRON_CONDOR,
        StrategyClass.LONG_STRADDLE,
    ]
    closes = features["close"].reset_index(drop=True)
    labels: list[str] = []

    for idx in range(len(features)):
        future = closes.iloc[idx + 1 : idx + 1 + horizon_bars]
        if len(future) < horizon_bars:
            labels.append(StrategyClass.NO_TRADE.value)
            continue

        row = features.iloc[idx]
        perf = {s.value: simulate_return(s, row, future) for s in candidates}
        best_label, best_ret = max(perf.items(), key=lambda x: x[1])
        labels.append(best_label if best_ret > 0 else StrategyClass.NO_TRADE.value)

    return pd.Series(labels, index=features.index, name="label")


def evaluate_predictions(
    features: pd.DataFrame,
    predicted_labels: pd.Series,
    horizon_bars: int = 10,
) -> dict:
    closes = features["close"].reset_index(drop=True)
    pnl = []

    for idx, label in enumerate(predicted_labels.tolist()):
        strategy = StrategyClass(label)
        if strategy == StrategyClass.NO_TRADE:
            continue
        future = closes.iloc[idx + 1 : idx + 1 + horizon_bars]
        if len(future) < horizon_bars:
            continue
        pnl.append(simulate_return(strategy, features.iloc[idx], future))

    if not pnl:
        return {"total_return": 0.0, "win_rate": 0.0, "avg_return_per_trade": 0.0, "trades": 0}

    arr = np.array(pnl)
    return {
        "total_return": float(arr.sum()),
        "win_rate": float((arr > 0).mean()),
        "avg_return_per_trade": float(arr.mean()),
        "trades": len(pnl),
    }
