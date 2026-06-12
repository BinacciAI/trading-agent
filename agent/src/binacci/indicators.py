"""Technical indicators (vectorized, numpy/pandas only — no TA-lib dep).

Includes the Binacci filter set: RSI, Bollinger, Ichimoku, volume,
and CMD (proprietary composite momentum/direction — implemented here as an
EMA-spread momentum confirmation, deliberately pluggable).
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def sma(s: pd.Series, period: int) -> pd.Series:
    return s.rolling(period, min_periods=period).mean()


def ema(s: pd.Series, period: int) -> pd.Series:
    return s.ewm(span=period, adjust=False, min_periods=period).mean()


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    out = 100 - 100 / (1 + rs)
    return out.fillna(50.0)


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    line = ema(close, fast) - ema(close, slow)
    sig = line.ewm(span=signal, adjust=False).mean()
    return line, sig, line - sig


def bollinger(close: pd.Series, period: int = 20, n_std: float = 2.0):
    mid = sma(close, period)
    std = close.rolling(period, min_periods=period).std(ddof=0)
    return mid - n_std * std, mid, mid + n_std * std


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    hl = df["high"] - df["low"]
    hc = (df["high"] - df["close"].shift()).abs()
    lc = (df["low"] - df["close"].shift()).abs()
    tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def ichimoku(df: pd.DataFrame, conversion: int = 9, base: int = 26, span_b: int = 52):
    """Returns (tenkan, kijun, senkou_a, senkou_b) — unshifted values."""
    def mid(period: int) -> pd.Series:
        return (
            df["high"].rolling(period, min_periods=period).max()
            + df["low"].rolling(period, min_periods=period).min()
        ) / 2.0

    tenkan = mid(conversion)
    kijun = mid(base)
    senkou_a = (tenkan + kijun) / 2.0
    senkou_b = mid(span_b)
    return tenkan, kijun, senkou_a, senkou_b


def cmd(close: pd.Series, fast: int = 9, slow: int = 26) -> pd.Series:
    """CMD — Composite Momentum/Direction (Binacci proprietary filter).

    Public stand-in: normalized EMA spread, in [-1, 1]-ish range. Positive
    and rising = bullish confirmation. Swap with the proprietary formula by
    replacing this function — every consumer goes through here.
    """
    spread = ema(close, fast) - ema(close, slow)
    return (spread / close).fillna(0.0) * 100.0


def volume_ratio(volume: pd.Series, lookback: int = 20) -> pd.Series:
    avg = volume.rolling(lookback, min_periods=lookback).mean()
    return (volume / avg.replace(0.0, np.nan)).fillna(0.0)


def to_dataframe(candles) -> pd.DataFrame:
    """List[Candle] -> OHLCV DataFrame indexed by timestamp."""
    return pd.DataFrame(
        {
            "ts": [c.ts for c in candles],
            "open": [c.open for c in candles],
            "high": [c.high for c in candles],
            "low": [c.low for c in candles],
            "close": [c.close for c in candles],
            "volume": [c.volume for c in candles],
        }
    ).set_index("ts")
