from __future__ import annotations

from enum import Enum


class StrategyClass(str, Enum):
    BULL_CALL_SPREAD = "BULL_CALL_SPREAD"
    BEAR_PUT_SPREAD = "BEAR_PUT_SPREAD"
    IRON_CONDOR = "IRON_CONDOR"
    LONG_STRADDLE = "LONG_STRADDLE"
    NO_TRADE = "NO_TRADE"


MODEL_FEATURE_COLUMNS = [
    "close",
    "sma_20",
    "sma_50",
    "trend_strength",
    "price_vs_sma20",
    "price_vs_sma50",
    "rsi_14",
    "macd",
    "macd_signal",
    "macd_hist",
    "atr_14",
    "rolling_std_20",
    "hist_vol_20",
    "bb_upper",
    "bb_lower",
    "bb_width",
    "volume_spike",
    "spy_trend_strength",
    "spy_price_vs_sma20",
    "spy_hist_vol_20",
]
