"""Vectorized, dependency-light reimplementations of the hot indicators.

Each function is a drop-in numeric equivalent of its pandas counterpart in
:mod:`indicators` — validated bit-for-bit in ``tests/test_fastind.py`` — but
computed with numpy + ``scipy.signal.lfilter`` instead of per-call pandas
rolling/ewm objects. The win is per-call overhead: a pandas ``ewm`` call is
~1ms; the lfilter recurrence is ~0.05ms, and the backtest calls these
thousands of times per run.

These operate on / return numpy arrays. The public :mod:`indicators` API keeps
its pandas signatures and delegates here when ``BINACCI_FAST_INDICATORS`` is on
(the default), wrapping the result back into a Series so every call site is
unchanged.
"""

from __future__ import annotations

import numpy as np
from scipy.signal import lfilter


def ewm(x: np.ndarray, alpha: float, min_periods: int) -> np.ndarray:
    """Exact match to ``Series.ewm(alpha=alpha, adjust=False,
    min_periods=min_periods).mean()`` for a series whose only NaNs (if any)
    are leading. y[0]=x[s]; y[t]=alpha*x[t]+(1-alpha)*y[t-1]."""
    x = np.asarray(x, dtype=float)
    out = np.full(x.shape, np.nan)
    valid = ~np.isnan(x)
    if not valid.any():
        return out
    s = int(np.argmax(valid))                      # first valid index
    xs = x[s:]
    # lfilter implements y[t] = alpha*x[t] + (1-alpha)*y[t-1], seeded so that
    # y[0] == xs[0] (matching pandas adjust=False).
    y = lfilter([alpha], [1.0, -(1.0 - alpha)], xs, zi=[(1.0 - alpha) * xs[0]])[0]
    out[s:] = y
    cnt = np.arange(1, len(xs) + 1)
    out[s:][cnt < min_periods] = np.nan
    return out


def _roll_view(x: np.ndarray, period: int):
    from numpy.lib.stride_tricks import sliding_window_view
    return sliding_window_view(np.asarray(x, dtype=float), period)


def rolling_mean(x: np.ndarray, period: int) -> np.ndarray:
    x = np.asarray(x, dtype=float)
    out = np.full(x.shape, np.nan)
    if len(x) >= period:
        out[period - 1:] = _roll_view(x, period).mean(axis=1)
    return out


def rolling_std_pop(x: np.ndarray, period: int) -> np.ndarray:
    """Population std (ddof=0) — matches ``rolling(period).std(ddof=0)``."""
    x = np.asarray(x, dtype=float)
    out = np.full(x.shape, np.nan)
    if len(x) >= period:
        out[period - 1:] = _roll_view(x, period).std(axis=1, ddof=0)
    return out


def rolling_max(x: np.ndarray, period: int) -> np.ndarray:
    x = np.asarray(x, dtype=float)
    out = np.full(x.shape, np.nan)
    if len(x) >= period:
        out[period - 1:] = _roll_view(x, period).max(axis=1)
    return out


def rolling_min(x: np.ndarray, period: int) -> np.ndarray:
    x = np.asarray(x, dtype=float)
    out = np.full(x.shape, np.nan)
    if len(x) >= period:
        out[period - 1:] = _roll_view(x, period).min(axis=1)
    return out


def sma(close: np.ndarray, period: int) -> np.ndarray:
    return rolling_mean(close, period)


def ema(close: np.ndarray, period: int) -> np.ndarray:
    return ewm(close, 2.0 / (period + 1), period)


def rsi(close: np.ndarray, period: int = 14) -> np.ndarray:
    c = np.asarray(close, dtype=float)
    delta = np.empty_like(c)
    delta[0] = np.nan
    delta[1:] = np.diff(c)
    gain = np.where(delta > 0, delta, 0.0)
    loss = np.where(delta < 0, -delta, 0.0)
    gain[0] = np.nan
    loss[0] = np.nan
    avg_gain = ewm(gain, 1.0 / period, period)
    avg_loss = ewm(loss, 1.0 / period, period)
    with np.errstate(divide="ignore", invalid="ignore"):
        rs = avg_gain / np.where(avg_loss == 0.0, np.nan, avg_loss)
        out = 100.0 - 100.0 / (1.0 + rs)
    return np.where(np.isnan(out), 50.0, out)


def bollinger(close: np.ndarray, period: int = 20, n_std: float = 2.0):
    mid = rolling_mean(close, period)
    std = rolling_std_pop(close, period)
    return mid - n_std * std, mid, mid + n_std * std


def atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 14) -> np.ndarray:
    high = np.asarray(high, float); low = np.asarray(low, float); close = np.asarray(close, float)
    prev_close = np.empty_like(close); prev_close[0] = np.nan; prev_close[1:] = close[:-1]
    hl = high - low
    hc = np.abs(high - prev_close)
    lc = np.abs(low - prev_close)
    tr = np.nanmax(np.vstack([hl, hc, lc]), axis=0)
    return ewm(tr, 1.0 / period, period)


def ichimoku(high: np.ndarray, low: np.ndarray, conversion: int = 9, base: int = 26, span_b: int = 52):
    def mid(period):
        return (rolling_max(high, period) + rolling_min(low, period)) / 2.0
    tenkan = mid(conversion)
    kijun = mid(base)
    senkou_a = (tenkan + kijun) / 2.0
    senkou_b = mid(span_b)
    return tenkan, kijun, senkou_a, senkou_b


def cmd(close: np.ndarray, fast: int = 9, slow: int = 26) -> np.ndarray:
    close = np.asarray(close, float)
    spread = ema(close, fast) - ema(close, slow)
    out = spread / close
    out = np.where(np.isnan(out), 0.0, out)
    return out * 100.0


def volume_ratio(volume: np.ndarray, lookback: int = 20) -> np.ndarray:
    volume = np.asarray(volume, float)
    avg = rolling_mean(volume, lookback)
    with np.errstate(divide="ignore", invalid="ignore"):
        out = volume / np.where(avg == 0.0, np.nan, avg)
    return np.where(np.isnan(out), 0.0, out)
