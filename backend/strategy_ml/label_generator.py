from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from strategy_ml.backtester import StrategyBacktester
from strategy_ml.types import StrategyClass


@dataclass(frozen=True)
class RuleThresholds:
    bullish_trend_min: float = 0.0
    bearish_trend_max: float = 0.0
    low_vol_max: float = 0.28
    high_vol_min: float = 0.40
    rsi_bull_min: float = 52.0
    rsi_bear_max: float = 48.0
    confidence_gap: float = 0.01


def generate_rule_based_labels(
    features: pd.DataFrame,
    thresholds: RuleThresholds = RuleThresholds(),
) -> pd.Series:
    labels = []
    for _, row in features.iterrows():
        trend = row.get("trend_strength", np.nan)
        rsi = row.get("rsi_14", np.nan)
        hist_vol = row.get("hist_vol_20", np.nan)
        macd_hist = row.get("macd_hist", np.nan)
        bb_width = row.get("bb_width", np.nan)

        if np.isnan(trend) or np.isnan(rsi) or np.isnan(hist_vol):
            labels.append(StrategyClass.NO_TRADE.value)
            continue

        bullish = trend > thresholds.bullish_trend_min and rsi >= thresholds.rsi_bull_min and macd_hist > 0
        bearish = trend < thresholds.bearish_trend_max and rsi <= thresholds.rsi_bear_max and macd_hist < 0
        low_vol = hist_vol <= thresholds.low_vol_max
        high_vol = hist_vol >= thresholds.high_vol_min

        if bullish and low_vol:
            labels.append(StrategyClass.BULL_CALL_SPREAD.value)
        elif bearish and low_vol:
            labels.append(StrategyClass.BEAR_PUT_SPREAD.value)
        elif abs(trend) < thresholds.confidence_gap and high_vol:
            labels.append(StrategyClass.IRON_CONDOR.value)
        elif not np.isnan(bb_width) and bb_width < 0.06 and hist_vol < 0.22:
            labels.append(StrategyClass.LONG_STRADDLE.value)
        else:
            labels.append(StrategyClass.NO_TRADE.value)

    return pd.Series(labels, index=features.index, name="rule_label")


def generate_performance_optimized_labels(
    features: pd.DataFrame,
    horizon_bars: int = 10,
    backtester: StrategyBacktester | None = None,
) -> pd.Series:
    engine = backtester or StrategyBacktester()
    return engine.relabel_best_strategy(features, horizon_bars=horizon_bars)
