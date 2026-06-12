"""The five Binacci simulations.

Background (24/7), producing reference points:
* **Sim01 — Cold start.** On boot/restart: replay ~1 year of history per
  symbol so every coin immediately has a current reference point.
* **Sim02 — Reference updates.** Continuously refresh reference points from
  Fibonacci retracements, candles, Fibonacci pivots, divergences, local
  max/min.
* **Sim03 — Clean entry references.** Same anchors but deliberately
  WITHOUT entry filters, tracking volume/RSI/Ichimoku/Bollinger context
  separately — references must stay undistorted.

Entry decision:
* **SimA — Entry zone.** Are we in a zone where opening is allowed at all?
  Fibonacci levels, hidden divergences, Bollinger oversold/overbought,
  filter checks (CMD, BB, volume).
* **SimB — Entry level.** WHICH price to enter at: logarithmic S/R,
  Fibonacci pivots, Fibonacci retracements, trend channels. Always a level,
  never market.

If any step of the chain reference -> zone -> filters -> macro -> level
fails, there is no entry. The bot does not guess; it waits for the whole
chain to align.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

from .config import SimulationConfig, FilterConfig, Timeframe
from .divergence import find_divergences, recent
from .indicators import bollinger, cmd, ichimoku, rsi, volume_ratio
from .levels import (
    Level,
    fib_pivots,
    fib_retracements,
    last_swing,
    local_extrema,
    log_support_resistance,
    near,
    trend_channel,
)
from .models import Candle, RefKind, ReferencePoint, Side


# --------------------------------------------------------------------------
# Background simulations: reference points
# --------------------------------------------------------------------------

@dataclass
class ReferenceBook:
    """Latest reference points per (symbol, timeframe)."""

    refs: dict[tuple[str, Timeframe], ReferencePoint] = field(default_factory=dict)

    def update(self, ref: ReferencePoint) -> None:
        self.refs[(ref.symbol, ref.timeframe)] = ref

    def get(self, symbol: str, tf: Timeframe) -> Optional[ReferencePoint]:
        return self.refs.get((symbol, tf))


def derive_reference(
    symbol: str,
    tf: Timeframe,
    df: pd.DataFrame,
    cfg: SimulationConfig,
    clean: bool,
) -> Optional[ReferencePoint]:
    """Core anchor derivation shared by Sim01/Sim02/Sim03.

    Maximum minima/maxima are the critical anchors; divergences and fib
    structures refine them.
    """
    if len(df) < cfg.extrema_window * 2 + 2:
        return None
    mins, maxs = local_extrema(df, cfg.extrema_window)
    if not mins and not maxs:
        return None

    last_min_i = mins[-1] if mins else -1
    last_max_i = maxs[-1] if maxs else -1

    # The freshest extremum wins; divergence at that pivot upgrades it.
    if last_min_i >= last_max_i:
        i, kind = last_min_i, RefKind.LOCAL_MIN
        price = float(df["low"].iloc[i])
    else:
        i, kind = last_max_i, RefKind.LOCAL_MAX
        price = float(df["high"].iloc[i])

    divs = find_divergences(df, cfg.divergence_lookback, min_gap=cfg.divergence_min_gap)
    div_at_pivot = any(abs(d.i2 - (i - (len(df) - cfg.divergence_lookback))) <= 2 for d in divs) if divs else False
    if div_at_pivot:
        kind = RefKind.DIVERGENCE

    return ReferencePoint(
        symbol=symbol,
        timeframe=tf,
        kind=kind,
        price=price,
        ts=df.index[i].to_pydatetime() if hasattr(df.index[i], "to_pydatetime") else df.index[i],
        clean=clean,
        meta={"bar_index": int(i), "divergence": div_at_pivot},
    )


class Sim01ColdStart:
    """One-shot at server start: replay history so every coin has a fresh
    reference before the bot even thinks about an entry."""

    def __init__(self, cfg: SimulationConfig):
        self.cfg = cfg

    def run(self, symbol: str, tf: Timeframe, history: pd.DataFrame, book: ReferenceBook) -> Optional[ReferencePoint]:
        ref = derive_reference(symbol, tf, history, self.cfg, clean=False)
        if ref:
            book.update(ref)
        return ref


class Sim02ReferenceUpdate:
    """Continuous, parallel: refresh references from fib corrections,
    candles, fib pivots, divergences, local extrema."""

    def __init__(self, cfg: SimulationConfig):
        self.cfg = cfg

    def step(self, symbol: str, tf: Timeframe, df: pd.DataFrame, book: ReferenceBook) -> Optional[ReferencePoint]:
        ref = derive_reference(symbol, tf, df, self.cfg, clean=False)
        if ref:
            prev = book.get(symbol, tf)
            if prev is None or ref.ts >= prev.ts:
                book.update(ref)
        return ref


class Sim03CleanReference:
    """Entry-grade references, updated WITHOUT entry filters so the anchor
    stays undistorted. Volume/RSI/Ichimoku/Bollinger context is computed and
    attached as metadata, never used to veto the anchor itself."""

    def __init__(self, cfg: SimulationConfig, fcfg: FilterConfig):
        self.cfg = cfg
        self.fcfg = fcfg

    def step(self, symbol: str, tf: Timeframe, df: pd.DataFrame, book: ReferenceBook) -> Optional[ReferencePoint]:
        ref = derive_reference(symbol, tf, df, self.cfg, clean=True)
        if ref is None:
            return None
        f = self.fcfg
        close = df["close"]
        lo, mid, up = bollinger(close, f.bollinger_period, f.bollinger_std)
        tenkan, kijun, sa, sb = ichimoku(df, f.ichimoku_conversion, f.ichimoku_base, f.ichimoku_span_b)
        ref.meta.update(
            rsi=float(rsi(close, f.rsi_period).iloc[-1]),
            bb_pos=float((close.iloc[-1] - lo.iloc[-1]) / max(up.iloc[-1] - lo.iloc[-1], 1e-12)),
            volume_ratio=float(volume_ratio(df["volume"], f.volume_lookback).iloc[-1]),
            ichimoku_above_cloud=bool(close.iloc[-1] > max(sa.iloc[-1], sb.iloc[-1])),
        )
        book.update(ref)
        return ref


# --------------------------------------------------------------------------
# Entry simulations
# --------------------------------------------------------------------------

@dataclass(slots=True)
class ZoneAssessment:
    in_zone: bool
    side: Side
    reasons: list[str]
    filters_ok: bool
    filter_detail: dict


class SimAEntryZone:
    """'Are we in a zone where opening is allowed at all?'

    Long zone evidence: price near a fib retracement of the last impulse,
    a recent hidden bullish divergence, or price at/below the lower
    Bollinger band. Then the filter set (CMD, BB, volume) must confirm a
    *reaction* — not a guess.
    """

    def __init__(self, scfg: SimulationConfig, fcfg: FilterConfig):
        self.scfg = scfg
        self.fcfg = fcfg

    def assess(self, df: pd.DataFrame, side: Side = Side.LONG) -> ZoneAssessment:
        reasons: list[str] = []
        close = df["close"]
        price = float(close.iloc[-1])

        # --- zone evidence ---
        swing = last_swing(df, self.scfg.extrema_window)
        if swing:
            lo_p, hi_p = swing
            if hi_p > lo_p:
                for lvl in fib_retracements(lo_p, hi_p, self.scfg.fib_levels):
                    if near(price, lvl.price, self.scfg.level_tolerance_pct * 2):
                        reasons.append(f"fib_{lvl.meta['ratio']}")
                        break

        divs = find_divergences(
            df, self.scfg.divergence_lookback, min_gap=self.scfg.divergence_min_gap,
            rsi_period=self.fcfg.rsi_period,
        )
        wanted = ("hidden_bull", "regular_bull") if side is Side.LONG else ("hidden_bear", "regular_bear")
        if recent(divs, wanted, within_last=10, total_len=min(len(df), self.scfg.divergence_lookback)):
            reasons.append("divergence")

        f = self.fcfg
        lo_b, mid_b, up_b = bollinger(close, f.bollinger_period, f.bollinger_std)
        if side is Side.LONG and price <= float(lo_b.iloc[-1]) * (1 + f.bollinger_std * 0.001):
            reasons.append("bb_lower")
        if side is Side.SHORT and price >= float(up_b.iloc[-1]) * (1 - f.bollinger_std * 0.001):
            reasons.append("bb_upper")

        in_zone = len(reasons) >= 1

        # --- filter confirmation (CMD, BB position, volume, RSI) ---
        cmd_series = cmd(close, f.cmd_fast, f.cmd_slow)
        cmd_now, cmd_prev = float(cmd_series.iloc[-1]), float(cmd_series.iloc[-2])
        rsi_now = float(rsi(close, f.rsi_period).iloc[-1])
        vol_ratio = float(volume_ratio(df["volume"], f.volume_lookback).iloc[-1])

        if side is Side.LONG:
            cmd_ok = cmd_now > cmd_prev          # momentum turning up = reaction
            rsi_ok = rsi_now <= f.rsi_overbought  # not chasing an overbought move
            bb_ok = price < float(up_b.iloc[-1])
        else:
            cmd_ok = cmd_now < cmd_prev
            rsi_ok = rsi_now >= f.rsi_oversold
            bb_ok = price > float(lo_b.iloc[-1])
        vol_ok = vol_ratio >= f.volume_min_ratio

        detail = {
            "cmd": cmd_now, "cmd_rising": cmd_ok, "rsi": rsi_now, "rsi_ok": rsi_ok,
            "volume_ratio": vol_ratio, "volume_ok": vol_ok, "bb_ok": bb_ok,
        }
        filters_ok = cmd_ok and rsi_ok and vol_ok and bb_ok
        return ZoneAssessment(in_zone=in_zone, side=side, reasons=reasons,
                              filters_ok=filters_ok, filter_detail=detail)


class SimBEntryLevel:
    """'At WHICH level do we enter?' — always by level, never by market.

    Candidates: logarithmic S/R, fib pivots, fib retracements, trend
    channels. Picks the strongest level at/just below current price (long).
    """

    def __init__(self, scfg: SimulationConfig):
        self.scfg = scfg

    def candidate_levels(self, df: pd.DataFrame) -> list[Level]:
        out: list[Level] = []
        out += log_support_resistance(df)
        out += fib_pivots(df)
        swing = last_swing(df, self.scfg.extrema_window)
        if swing and swing[1] > swing[0]:
            out += fib_retracements(swing[0], swing[1], self.scfg.fib_levels)
        out += trend_channel(df)
        return out

    def pick(self, df: pd.DataFrame, side: Side = Side.LONG) -> Optional[Level]:
        price = float(df["close"].iloc[-1])
        levels = self.candidate_levels(df)
        if side is Side.LONG:
            # nearest level at or below price, within a sane band (<=3% away)
            below = [l for l in levels if l.price <= price * (1 + self.scfg.level_tolerance_pct / 100)
                     and l.price >= price * 0.97]
            if not below:
                return None
            below.sort(key=lambda l: (-(l.price), -l.strength))
            return below[0]
        above = [l for l in levels if l.price >= price * (1 - self.scfg.level_tolerance_pct / 100)
                 and l.price <= price * 1.03]
        if not above:
            return None
        above.sort(key=lambda l: (l.price, -l.strength))
        return above[0]

    def touched(self, candle: Candle, level: Level, side: Side, tol_pct: float) -> bool:
        """Did this candle touch the level (limit fill plausible)?"""
        band = level.price * tol_pct / 100.0
        if side is Side.LONG:
            return candle.low <= level.price + band
        return candle.high >= level.price - band
