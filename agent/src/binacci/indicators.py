"""Technical indicators (vectorized, numpy/pandas only — no TA-lib dep).

Includes the Binacci filter set: RSI, Bollinger, Ichimoku, volume, and CMD
(proprietary composite momentum/direction — EMA-spread stand-in, pluggable).

Three backends, all numerically identical (validated in tests/test_fastind.py):

1. pandas reference (BINACCI_FAST_INDICATORS=0).
2. vectorized numpy/scipy fast path (default) — same math, ~10-15x less per-call
   overhead.
3. precompute path (BINACCI_FAST_BACKTEST=1, opt-in): when a backtest primes the
   full OHLCV frame, each indicator is computed ONCE over the whole series and
   per-bar calls return a slice. Indicators are causal (value at bar i depends
   only on bars <= i), so the precompute introduces no lookahead — the value at
   the window's last bar matches the windowed recompute to fp noise. Gated off
   by default and proven trade-identical by the equivalence harness before use.

Public signatures and return types (pd.Series) are unchanged across all three.
"""

from __future__ import annotations

import os

import numpy as np
import pandas as pd

from . import fastind as _F

#: Vectorized fast path (read once at import; monkeypatchable in tests).
FAST_INDICATORS: bool = os.environ.get("BINACCI_FAST_INDICATORS", "1").strip().lower() not in ("0", "false", "no", "off")

# --------------------------------------------------------------------------
# Precompute context (set by the backtest; None in live/normal use).
# --------------------------------------------------------------------------
_PRE: dict | None = None


def prime_precompute(full_df: pd.DataFrame) -> None:
    """Register the full OHLCV frame so per-bar indicator calls become slices of
    a single full-series computation (lazily cached per indicator+params)."""
    global _PRE
    _PRE = {
        "index": full_df.index,
        "close": full_df["close"].to_numpy(),
        "high": full_df["high"].to_numpy(),
        "low": full_df["low"].to_numpy(),
        "volume": full_df["volume"].to_numpy(),
        "cache": {},
    }


def clear_precompute() -> None:
    global _PRE
    _PRE = None


def _bounds(index) -> tuple | None:
    """If `index` is a contiguous tail-slice of the primed full index, return
    (lo, hi); else None. Stateless — keyed on the index values (timestamps), not
    object identity (Python reuses ids after GC, which would alias slices)."""
    if _PRE is None:
        return None
    fidx = _PRE["index"]
    try:
        lo = fidx.get_loc(index[0])
    except Exception:
        return None
    if not isinstance(lo, (int, np.integer)):
        return None
    lo = int(lo)
    hi = lo + len(index)
    # monotonic-unique index => endpoint + length check proves contiguity
    if hi <= len(fidx) and fidx[hi - 1] == index[-1]:
        return lo, hi
    return None


def _cached(name, params, builder):
    arr = _PRE["cache"].get((name, params))
    if arr is None:
        arr = builder()
        _PRE["cache"][(name, params)] = arr
    return arr


def sma(s: pd.Series, period: int) -> pd.Series:
    if FAST_INDICATORS and _PRE is not None:
        b = _bounds(s.index)
        if b is not None:
            arr = _cached("sma", period, lambda: _F.sma(_PRE["close"], period))
            return pd.Series(arr[b[0]:b[1]], index=s.index)
    if FAST_INDICATORS:
        return pd.Series(_F.sma(s.to_numpy(), period), index=s.index)
    return s.rolling(period, min_periods=period).mean()


def ema(s: pd.Series, period: int) -> pd.Series:
    if FAST_INDICATORS and _PRE is not None:
        b = _bounds(s.index)
        if b is not None:
            arr = _cached("ema", period, lambda: _F.ema(_PRE["close"], period))
            return pd.Series(arr[b[0]:b[1]], index=s.index)
    if FAST_INDICATORS:
        return pd.Series(_F.ema(s.to_numpy(), period), index=s.index)
    return s.ewm(span=period, adjust=False, min_periods=period).mean()


def rsi(close: pd.Series, period: int = 14, _skip_precompute: bool = False) -> pd.Series:
    if FAST_INDICATORS and _PRE is not None and not _skip_precompute:
        b = _bounds(close.index)
        if b is not None:
            arr = _cached("rsi", period, lambda: _F.rsi(_PRE["close"], period))
            return pd.Series(arr[b[0]:b[1]], index=close.index)
    if FAST_INDICATORS:
        return pd.Series(_F.rsi(close.to_numpy(), period), index=close.index)
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
    if FAST_INDICATORS and _PRE is not None:
        b = _bounds(close.index)
        if b is not None:
            lo, mid, up = _cached(("boll", n_std), period,
                                  lambda: _F.bollinger(_PRE["close"], period, n_std))
            i, j = b
            return (pd.Series(lo[i:j], index=close.index),
                    pd.Series(mid[i:j], index=close.index),
                    pd.Series(up[i:j], index=close.index))
    if FAST_INDICATORS:
        lo, mid, up = _F.bollinger(close.to_numpy(), period, n_std)
        return (pd.Series(lo, index=close.index), pd.Series(mid, index=close.index),
                pd.Series(up, index=close.index))
    mid = sma(close, period)
    std = close.rolling(period, min_periods=period).std(ddof=0)
    return mid - n_std * std, mid, mid + n_std * std


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    if FAST_INDICATORS and _PRE is not None:
        b = _bounds(df.index)
        if b is not None:
            arr = _cached("atr", period,
                          lambda: _F.atr(_PRE["high"], _PRE["low"], _PRE["close"], period))
            return pd.Series(arr[b[0]:b[1]], index=df.index)
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
    if FAST_INDICATORS and _PRE is not None:
        b = _bounds(df.index)
        if b is not None:
            t, k, sa, sb = _cached("ich", (conversion, base, span_b),
                                   lambda: _F.ichimoku(_PRE["high"], _PRE["low"], conversion, base, span_b))
            i, j = b; idx = df.index
            return (pd.Series(t[i:j], index=idx), pd.Series(k[i:j], index=idx),
                    pd.Series(sa[i:j], index=idx), pd.Series(sb[i:j], index=idx))
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

    Public stand-in: normalized EMA spread. Positive and rising = bullish.
    Swap with the proprietary formula by replacing this function — every
    consumer goes through here.
    """
    if FAST_INDICATORS and _PRE is not None:
        b = _bounds(close.index)
        if b is not None:
            arr = _cached("cmd", (fast, slow), lambda: _F.cmd(_PRE["close"], fast, slow))
            return pd.Series(arr[b[0]:b[1]], index=close.index)
    if FAST_INDICATORS:
        return pd.Series(_F.cmd(close.to_numpy(), fast, slow), index=close.index)
    spread = ema(close, fast) - ema(close, slow)
    return (spread / close).fillna(0.0) * 100.0


def volume_ratio(volume: pd.Series, lookback: int = 20) -> pd.Series:
    if FAST_INDICATORS and _PRE is not None:
        b = _bounds(volume.index)
        if b is not None:
            arr = _cached("vr", lookback, lambda: _F.volume_ratio(_PRE["volume"], lookback))
            return pd.Series(arr[b[0]:b[1]], index=volume.index)
    if FAST_INDICATORS:
        return pd.Series(_F.volume_ratio(volume.to_numpy(), lookback), index=volume.index)
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
