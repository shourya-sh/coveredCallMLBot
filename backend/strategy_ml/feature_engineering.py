from __future__ import annotations

import numpy as np
import pandas as pd


def _rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    up = delta.clip(lower=0)
    down = -delta.clip(upper=0)
    roll_up = up.ewm(alpha=1 / period, adjust=False).mean()
    roll_down = down.ewm(alpha=1 / period, adjust=False).mean()
    rs = roll_up / roll_down.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> tuple[pd.Series, pd.Series, pd.Series]:
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd = ema_fast - ema_slow
    macd_signal = macd.ewm(span=signal, adjust=False).mean()
    macd_hist = macd - macd_signal
    return macd, macd_signal, macd_hist


def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    prev_close = df["close"].shift(1)
    tr = pd.concat(
        [
            (df["high"] - df["low"]).abs(),
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.rolling(period, min_periods=period).mean()


def build_feature_frame(candles: pd.DataFrame, spy_candles: pd.DataFrame | None = None) -> pd.DataFrame:
    """
    Build time-aligned features with no lookahead bias.

    Expected columns for candles and spy_candles:
    datetime, open, high, low, close, volume
    """
    df = candles.copy()
    if df.empty:
        return df

    df = df.sort_values("datetime").reset_index(drop=True)
    for col in ["open", "high", "low", "close", "volume"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df["sma_20"] = df["close"].rolling(20, min_periods=20).mean()
    df["sma_50"] = df["close"].rolling(50, min_periods=50).mean()
    df["trend_strength"] = df["sma_20"] - df["sma_50"]
    df["price_vs_sma20"] = (df["close"] / df["sma_20"]) - 1
    df["price_vs_sma50"] = (df["close"] / df["sma_50"]) - 1

    df["rsi_14"] = _rsi(df["close"], period=14)
    macd, macd_signal, macd_hist = _macd(df["close"])
    df["macd"] = macd
    df["macd_signal"] = macd_signal
    df["macd_hist"] = macd_hist

    df["atr_14"] = _atr(df, period=14)
    df["rolling_std_20"] = df["close"].pct_change().rolling(20, min_periods=20).std()
    df["hist_vol_20"] = df["rolling_std_20"] * np.sqrt(252)

    rolling_mean = df["close"].rolling(20, min_periods=20).mean()
    rolling_std = df["close"].rolling(20, min_periods=20).std()
    df["bb_upper"] = rolling_mean + (2 * rolling_std)
    df["bb_lower"] = rolling_mean - (2 * rolling_std)
    df["bb_width"] = (df["bb_upper"] - df["bb_lower"]) / rolling_mean

    volume_avg = df["volume"].rolling(20, min_periods=20).mean()
    df["volume_spike"] = df["volume"] / volume_avg

    if spy_candles is not None and not spy_candles.empty:
        ctx = spy_candles.copy().sort_values("datetime")
        ctx["close"] = pd.to_numeric(ctx["close"], errors="coerce")
        ctx["sma_20"] = ctx["close"].rolling(20, min_periods=20).mean()
        ctx["sma_50"] = ctx["close"].rolling(50, min_periods=50).mean()
        ctx["spy_trend_strength"] = ctx["sma_20"] - ctx["sma_50"]
        ctx["spy_price_vs_sma20"] = (ctx["close"] / ctx["sma_20"]) - 1
        ctx["spy_hist_vol_20"] = ctx["close"].pct_change().rolling(20, min_periods=20).std() * np.sqrt(252)
        df = df.merge(
            ctx[["datetime", "spy_trend_strength", "spy_price_vs_sma20", "spy_hist_vol_20"]],
            on="datetime",
            how="left",
        )
    else:
        df["spy_trend_strength"] = np.nan
        df["spy_price_vs_sma20"] = np.nan
        df["spy_hist_vol_20"] = np.nan

    # Forward-fill context only; avoids peeking into future bars.
    df[["spy_trend_strength", "spy_price_vs_sma20", "spy_hist_vol_20"]] = df[
        ["spy_trend_strength", "spy_price_vs_sma20", "spy_hist_vol_20"]
    ].ffill()

    return df
