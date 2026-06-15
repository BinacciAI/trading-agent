"""Technical indicators (vectorized, numpy/pandas only — no TA-lib dep).

Includes the Binacci filter set: RSI, Bollinger, Ichimoku, volume,
and CMD (proprietary composite momentum/direction — implemented here as an
EMA-spread momentum confirmation, deliberately pluggable).

Each indicator has two backends with identical numeric output (validated in
tests/test_fastind.py): a pandas reference, and a vectorized numpy/scipy fast
path in :mod:`fastind` that avoids per-call pandas overhead (~10-15x faster per
call). The fast path is the default; disable with BINACCI_FAST_INDICATORS=0.
Public signatures and return types (pd.Series) are unchanged either way.
"""

from __future__ import annotations

import os

import numpy as np
import pandas as pd

from . import fastind as _F

#: Module-level toggle (read once at import; monkeypatchable in tests).
FAST_INDICATORS: bool = os.environ.get("BINACCI_FAST_INDICATORS", "1").strip().lower() not in ("0", "false", "no", "off")


def _wrap(values: np.ndarray, like: pd.Series) -> pd.Series:
    return pd.Series(values, index=like.index)


def sma(s: pd.Series, period: int) -> pd.Series:
    if FAST_INDICATORS:
        return _wrap(_F.sma(s.to_numpy(), period), s)
    return s.rolling(period, min_periods=period).mean()


def ema(s: pd.Series, period: int) -> pd.Series:
    if FAST_INDICATORS:
        return _wrap(_F.ema(s.to_numpy(), period), s)
    return s.ewm(span=period, adjust=False, min_periods=period).mean()


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    if FAST_INDICATORS:
        return _wrap(_F.rsi(close.to_numpy(), period), close)
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
    if FAST_INDICATORS:
        lo, mid, up = _F.bollinger(close.to_numpy(), period, n_std)
        return _wrap(lo, close), _wrap(mid, close), _wrap(up, close)
    mid = sma(close, period)
    std = close.rolling(period, min_periods=period).std(ddof=0)
    return mid - n_std * std, mid, mid + n_std * std


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    if FAST_INDICATORS:
        vals = _F.atr(df["high"].to_numpy(), df["low"].to_numpy(), df["close"].to_numpy(), period)
        return pd.Series(vals, index=df.index)
    hl = df["high"] - df["low"]
    hc = (df["high"] - df["close"].shift()).abs()
    lc = (df["low"] - df["close"].shift()).abs()
    tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def ichimoku(df: pd.DataFrame, conversion: int = 9, base: int = 26, span_b: int = 52):
    """Returns (tenkan, kijun, senkou_a, senkou_b) — unshifted values."""
    if FAST_INDICATORS:
        t, k, sa, sb = _F.ichimoku(df["high"].to_numpy(), df["low"].to_numpy(), conversion, base, span_b)
        idx = df.index
        return (pd.Series(t, index=idx), pd.Series(k, index=idx),
                pd.Series(sa, index=idx), pd.Series(sb, index=idx))

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
    if FAST_INDICATORS:
        return _wrap(_F.cmd(close.to_numpy(), fast, slow), close)
    spread = ema(close, fast) - ema(close, slow)
    return (spread / close).fillna(0.0) * 100.0


def volume_ratio(volume: pd.Series, lookback: int = 20) -> pd.Series:
    if FAST_INDICATORS:
        return _wrap(_F.volume_ratio(volume.to_numpy(), lookback), volume)
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
