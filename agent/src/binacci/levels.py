"""Level construction: Fibonacci retracements/pivots, logarithmic S/R,
local extrema, trend channels.

Entries are always taken AT a level (limit), never "at market". SimB uses
these to pick the concrete entry price.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(slots=True)
class Level:
    price: float
    kind: str       # fib | fib_pivot | log_sr | channel | extremum
    strength: float  # 0..1 relative confidence
    meta: dict


def local_extrema(df: pd.DataFrame, window: int = 12) -> tuple[list[int], list[int]]:
    """Indices of confirmed local minima / maxima (window bars each side)."""
    lows = df["low"].to_numpy()
    highs = df["high"].to_numpy()
    n = len(df)
    mins, maxs = [], []
    for i in range(window, n - window):
        seg_l = lows[i - window : i + window + 1]
        seg_h = highs[i - window : i + window + 1]
        if lows[i] == seg_l.min():
            mins.append(i)
        if highs[i] == seg_h.max():
            maxs.append(i)
    return mins, maxs


def last_swing(df: pd.DataFrame, window: int = 12) -> tuple[float, float] | None:
    """(swing_low, swing_high) of the most recent completed impulse."""
    mins, maxs = local_extrema(df, window)
    if not mins or not maxs:
        return None
    lo_i, hi_i = mins[-1], maxs[-1]
    return float(df["low"].iloc[lo_i]), float(df["high"].iloc[hi_i])


def fib_retracements(
    swing_low: float, swing_high: float, levels=(0.236, 0.382, 0.5, 0.618, 0.786)
) -> list[Level]:
    """Retracement levels of the last impulse (support for longs)."""
    span = swing_high - swing_low
    out = []
    for f in levels:
        price = swing_high - span * f
        strength = 1.0 if abs(f - 0.618) < 1e-9 else (0.85 if f in (0.5, 0.382) else 0.7)
        out.append(Level(price=price, kind="fib", strength=strength, meta={"ratio": f}))
    return out


def fib_pivots(df: pd.DataFrame) -> list[Level]:
    """Fibonacci pivot points from the previous completed period."""
    prev = df.iloc[-2] if len(df) >= 2 else df.iloc[-1]
    p = (prev["high"] + prev["low"] + prev["close"]) / 3.0
    rng = prev["high"] - prev["low"]
    out = [Level(price=float(p), kind="fib_pivot", strength=0.8, meta={"name": "P"})]
    for name, f, sign in (
        ("S1", 0.382, -1), ("S2", 0.618, -1), ("S3", 1.0, -1),
        ("R1", 0.382, +1), ("R2", 0.618, +1), ("R3", 1.0, +1),
    ):
        out.append(
            Level(
                price=float(p + sign * f * rng),
                kind="fib_pivot",
                strength=0.75 if f < 1.0 else 0.6,
                meta={"name": name},
            )
        )
    return out


def log_support_resistance(
    df: pd.DataFrame, n_bins: int = 48, top_k: int = 8, window: int = 6
) -> list[Level]:
    """Logarithmic support/resistance: cluster extrema in log-price space."""
    mins, maxs = local_extrema(df, window)
    pts = np.concatenate(
        [df["low"].to_numpy()[mins], df["high"].to_numpy()[maxs]]
    ) if (mins or maxs) else np.array([])
    if pts.size == 0:
        return []
    logs = np.log(pts)
    hist, edges = np.histogram(logs, bins=n_bins)
    order = np.argsort(hist)[::-1][:top_k]
    out = []
    peak = hist.max() or 1
    for b in order:
        if hist[b] == 0:
            continue
        mask = (logs >= edges[b]) & (logs <= edges[b + 1])
        price = float(np.exp(logs[mask].mean()))
        out.append(
            Level(
                price=price,
                kind="log_sr",
                strength=float(hist[b] / peak),
                meta={"touches": int(hist[b])},
            )
        )
    return out


def trend_channel(df: pd.DataFrame, lookback: int = 120) -> list[Level]:
    """Linear-regression channel over the lookback; lower/upper bounds at
    the latest bar are tradable levels."""
    seg = df.tail(lookback)
    if len(seg) < 20:
        return []
    x = np.arange(len(seg), dtype=float)
    close = seg["close"].to_numpy()
    slope, intercept = np.polyfit(x, close, 1)
    fit = slope * x + intercept
    resid = close - fit
    width = float(np.percentile(np.abs(resid), 90))
    last_fit = float(fit[-1])
    return [
        Level(price=last_fit - width, kind="channel", strength=0.7,
              meta={"bound": "lower", "slope": float(slope)}),
        Level(price=last_fit + width, kind="channel", strength=0.7,
              meta={"bound": "upper", "slope": float(slope)}),
    ]


def near(price: float, level: float, tolerance_pct: float) -> bool:
    return abs(price - level) / level * 100.0 <= tolerance_pct
