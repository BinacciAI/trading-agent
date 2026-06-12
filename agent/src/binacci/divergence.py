"""Divergence detection — regular and hidden, on RSI by default.

SimA leans on *hidden* divergences (trend-continuation signals):
* Hidden bullish: price makes a HIGHER low, oscillator makes a LOWER low.
* Hidden bearish: price makes a LOWER high, oscillator makes a HIGHER high.
Regular divergences are also detected for reference-point construction.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .indicators import rsi as _rsi


@dataclass(slots=True)
class Divergence:
    kind: str        # regular_bull | regular_bear | hidden_bull | hidden_bear
    i1: int          # first pivot index
    i2: int          # second pivot index
    price1: float
    price2: float
    osc1: float
    osc2: float


def _pivot_lows(arr: np.ndarray, w: int) -> list[int]:
    return [
        i for i in range(w, len(arr) - w)
        if arr[i] == arr[i - w : i + w + 1].min()
    ]


def _pivot_highs(arr: np.ndarray, w: int) -> list[int]:
    return [
        i for i in range(w, len(arr) - w)
        if arr[i] == arr[i - w : i + w + 1].max()
    ]


def find_divergences(
    df: pd.DataFrame,
    lookback: int = 60,
    pivot_window: int = 3,
    min_gap: int = 5,
    rsi_period: int = 14,
) -> list[Divergence]:
    seg = df.tail(lookback)
    if len(seg) < pivot_window * 2 + min_gap + 2:
        return []
    lows = seg["low"].to_numpy()
    highs = seg["high"].to_numpy()
    osc = _rsi(seg["close"], rsi_period).to_numpy()

    out: list[Divergence] = []

    pl = _pivot_lows(lows, pivot_window)
    for a, b in zip(pl, pl[1:]):
        if b - a < min_gap:
            continue
        d = dict(i1=a, i2=b, price1=float(lows[a]), price2=float(lows[b]),
                 osc1=float(osc[a]), osc2=float(osc[b]))
        if lows[b] < lows[a] and osc[b] > osc[a]:
            out.append(Divergence(kind="regular_bull", **d))
        elif lows[b] > lows[a] and osc[b] < osc[a]:
            out.append(Divergence(kind="hidden_bull", **d))

    ph = _pivot_highs(highs, pivot_window)
    for a, b in zip(ph, ph[1:]):
        if b - a < min_gap:
            continue
        d = dict(i1=a, i2=b, price1=float(highs[a]), price2=float(highs[b]),
                 osc1=float(osc[a]), osc2=float(osc[b]))
        if highs[b] > highs[a] and osc[b] < osc[a]:
            out.append(Divergence(kind="regular_bear", **d))
        elif highs[b] < highs[a] and osc[b] > osc[a]:
            out.append(Divergence(kind="hidden_bear", **d))

    return out


def recent(divs: list[Divergence], kinds: tuple[str, ...], within_last: int, total_len: int) -> list[Divergence]:
    """Divergences of given kinds whose second pivot is within the last N bars."""
    cutoff = total_len - within_last
    return [d for d in divs if d.kind in kinds and d.i2 >= cutoff]
