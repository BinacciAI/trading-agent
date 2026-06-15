"""Binacci strategy portfolio — many independent opinions, one risk engine.

Binacci is not a single strategy. It runs a *portfolio* of strategies
concurrently, each scanning every (symbol, timeframe) stream and proposing
its own limit entry. Every proposal still flows through the SAME
deterministic :class:`~binacci.execution.ExecutionEngine` — the 30/70 margin
model, 5-slot cap, x4/x2 averaging, stepped trailing SL, and 30% kill
switch apply identically no matter which strategy opened the position.

Why a portfolio? The core reaction strategy is deliberately patient — it
waits for a full reference -> zone -> filter -> macro -> level chain. That
is correct, but it means whole categories of opportunity (clean trend
pullbacks, volatility-squeeze breakouts, capitulation reclaims) pass it by.
Adding orthogonal strategies widens the opportunity surface **without**
loosening a single risk rule: positions are unique per
(symbol, timeframe, strategy), so a quiet day for one strategy is a busy day
for another, and the slot cap / kill switch still bound total exposure.

Every strategy obeys the house invariant: **entries are limits at a concrete
level, never market.** A strategy returns the level; the orchestrator parks
it and only fills on a touch.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

from .config import StrategyConfig, Timeframe
from .indicators import bollinger, cmd, ema, rsi, volume_ratio
from .models import Side
from .simulations import SimAEntryZone, SimBEntryLevel


@dataclass(slots=True)
class StrategyProposal:
    """One strategy's proposed limit entry for a (symbol, timeframe)."""

    strategy: str
    side: Side
    level_price: float          # the limit price — fills on a touch
    level_kind: str
    strength: float             # 0..1 confidence, for ranking / audit
    reasons: list[str]
    target_pct: Optional[float] = None   # None -> orchestrator uses TF target
    requires_macro: bool = True
    meta: dict = field(default_factory=dict)


class Strategy:
    """Base class. A strategy is a pure function of recent OHLCV -> proposal.

    It does NOT touch the execution engine, slots, or macro — the
    orchestrator owns shared gating and lifecycle. A strategy only answers:
    "given this chart, is there a level I want to be a resting buyer at, and
    why?"
    """

    name: str = "base"
    #: If True, the orchestrator only runs this strategy when a fresh
    #: reference point exists for the (symbol, timeframe).
    requires_reference: bool = False
    #: If True, the macro gate must pass before this strategy's entry parks.
    requires_macro: bool = True
    #: Minimum completed bars needed before the strategy can be evaluated.
    min_bars: int = 60

    def __init__(self, cfg: StrategyConfig):
        self.cfg = cfg

    def propose(self, symbol: str, tf: Timeframe, df: pd.DataFrame,
                side: Side = Side.LONG) -> Optional[StrategyProposal]:
        raise NotImplementedError

    # -- shared helpers: clamp a limit near price, on the correct side --
    def _long_limit_ok(self, df: pd.DataFrame, level: float, max_below_pct: float = 4.0) -> bool:
        price = float(df["close"].iloc[-1])
        return price * (1 - max_below_pct / 100.0) <= level <= price * 1.001

    def _short_limit_ok(self, df: pd.DataFrame, level: float, max_above_pct: float = 4.0) -> bool:
        price = float(df["close"].iloc[-1])
        return price * 0.999 <= level <= price * (1 + max_above_pct / 100.0)

    def _limit_ok(self, df, level, side, band=4.0):
        return self._long_limit_ok(df, level, band) if side is Side.LONG else self._short_limit_ok(df, level, band)


# --------------------------------------------------------------------------
# 1) Reaction — the core 5-gate strategy, wrapped as one portfolio member
# --------------------------------------------------------------------------

class ReactionStrategy(Strategy):
    """The original Binacci reaction strategy: fib/divergence/Bollinger zone,
    CMD+RSI+volume filter confirmation, then a concrete log-S/R / fib level.
    Patient and high-conviction."""

    name = "reaction"
    requires_reference = True
    requires_macro = True

    def __init__(self, cfg: StrategyConfig):
        super().__init__(cfg)
        self.min_bars = cfg.sims.extrema_window * 2 + 4
        self._zone = SimAEntryZone(cfg.sims, cfg.filters)
        self._level = SimBEntryLevel(cfg.sims)

    def propose(self, symbol, tf, df, side=Side.LONG):
        zone = self._zone.assess(df, side)
        if not zone.in_zone or not zone.filters_ok:
            return None
        level = self._level.pick(df, side)
        if level is None:
            return None
        return StrategyProposal(
            strategy=self.name, side=side, level_price=level.price,
            level_kind=level.kind, strength=float(level.strength),
            reasons=list(zone.reasons), requires_macro=self.requires_macro,
            meta={"filters": zone.filter_detail, "level_strength": level.strength},
        )


# --------------------------------------------------------------------------
# 2) Momentum breakout — buy the retest of a Donchian breakout
# --------------------------------------------------------------------------

class MomentumBreakoutStrategy(Strategy):
    """A close above the prior N-bar high (Donchian breakout) with rising
    CMD momentum and a volume expansion signals trend ignition. We don't
    chase: we park a limit at the *retest* of the broken level (just below
    it) so the entry is still a level, never a market chase."""

    name = "momentum_breakout"
    requires_reference = False

    def __init__(self, cfg: StrategyConfig):
        super().__init__(cfg)
        self.bk = cfg.breakout
        self.requires_macro = self.bk.require_macro
        self.min_bars = max(self.bk.donchian_period + 5, 30)

    def propose(self, symbol, tf, df, side=Side.LONG):
        p = self.bk.donchian_period
        if len(df) < p + 2:
            return None
        close = df["close"]
        price = float(close.iloc[-1])
        cs = cmd(close, self.cfg.filters.cmd_fast, self.cfg.filters.cmd_slow)
        cmd_now, cmd_prev = float(cs.iloc[-1]), float(cs.iloc[-2])
        vol = float(volume_ratio(df["volume"], self.cfg.filters.volume_lookback).iloc[-1])
        if vol < self.bk.volume_min_ratio:
            return None
        target = self.cfg.target_for(tf) * self.bk.target_mult
        if side is Side.LONG:
            prior = float(df["high"].iloc[-(p + 1):-1].max())
            if not (price > prior and cmd_now > cmd_prev):
                return None
            level = prior * (1 - self.bk.retest_band_pct / 100.0)
            reasons = [f"breakout>{prior:.6g}", "cmd_rising", f"vol_x{vol:.2f}"]
            lk = "donchian_retest"
        else:
            prior = float(df["low"].iloc[-(p + 1):-1].min())
            if not (price < prior and cmd_now < cmd_prev):
                return None
            level = prior * (1 + self.bk.retest_band_pct / 100.0)
            reasons = [f"breakdown<{prior:.6g}", "cmd_falling", f"vol_x{vol:.2f}"]
            lk = "donchian_retest_short"
        if not self._limit_ok(df, level, side, self.bk.retest_band_pct + 1.0):
            return None
        return StrategyProposal(
            strategy=self.name, side=side, level_price=level,
            level_kind=lk, strength=min(1.0, vol / 2.0),
            reasons=reasons, target_pct=target, requires_macro=self.requires_macro,
            meta={"donchian": prior, "volume_ratio": vol},
        )


# --------------------------------------------------------------------------
# 3) Mean reversion — fade an oversold flush, enter on the reclaim
# --------------------------------------------------------------------------

class MeanReversionStrategy(Strategy):
    """Capitulation fade. When RSI is deeply oversold and price has pierced
    the lower Bollinger band, a reclaim back inside the band marks the snap.
    We park a limit at the lower band to buy the retest of the flush. This
    one does NOT require a risk-on macro light — it is explicitly a
    counter-trend dip buy — which is why it adds opportunity the trend
    strategies cannot."""

    name = "mean_reversion"
    requires_reference = False

    def __init__(self, cfg: StrategyConfig):
        super().__init__(cfg)
        self.mr = cfg.mean_reversion
        self.requires_macro = self.mr.require_macro
        self.min_bars = max(self.mr.bb_period + 5, self.cfg.filters.rsi_period + 5, 30)

    def propose(self, symbol, tf, df, side=Side.LONG):
        close = df["close"]
        lo, mid, up = bollinger(close, self.mr.bb_period, self.mr.bb_std)
        if pd.isna(lo.iloc[-1]) or pd.isna(up.iloc[-1]) or pd.isna(lo.iloc[-2]):
            return None
        r = float(rsi(close, self.cfg.filters.rsi_period).iloc[-1])
        price = float(close.iloc[-1])
        target = self.cfg.target_for(tf) * self.mr.target_mult
        if side is Side.LONG:
            if not (float(df["low"].iloc[-2]) <= float(lo.iloc[-2]) and r <= self.mr.rsi_oversold):
                return None
            level = float(lo.iloc[-1])
            if self.mr.require_reclaim and price < level:
                return None
            reasons = [f"rsi={r:.1f}<={self.mr.rsi_oversold}", "bb_lower_pierce", "reclaim"]
            lk = "bb_lower_reclaim"; strg = min(1.0, (self.mr.rsi_oversold - r + 10) / 30.0)
        else:
            if not (float(df["high"].iloc[-2]) >= float(up.iloc[-2]) and r >= self.mr.rsi_overbought):
                return None
            level = float(up.iloc[-1])
            if self.mr.require_reclaim and price > level:
                return None
            reasons = [f"rsi={r:.1f}>={self.mr.rsi_overbought}", "bb_upper_pierce", "reclaim"]
            lk = "bb_upper_reclaim"; strg = min(1.0, (r - self.mr.rsi_overbought + 10) / 30.0)
        if not self._limit_ok(df, level, side, 3.0):
            return None
        return StrategyProposal(
            strategy=self.name, side=side, level_price=level,
            level_kind=lk, strength=strg, reasons=reasons,
            target_pct=target, requires_macro=self.requires_macro,
            meta={"rsi": r, "band": level},
        )


# --------------------------------------------------------------------------
# 4) Trend follow — EMA stack aligned, enter the pullback to the mid EMA
# --------------------------------------------------------------------------

class TrendFollowStrategy(Strategy):
    """Ride an established uptrend. When the fast/mid/slow EMAs are stacked
    bullishly, the highest-probability low-risk entry is the pullback to the
    mid EMA. We park a limit there. The stepped trailing SL then lets the
    position run with the trend."""

    name = "trend_follow"
    requires_reference = False

    def __init__(self, cfg: StrategyConfig):
        super().__init__(cfg)
        self.tr = cfg.trend
        self.requires_macro = self.tr.require_macro
        self.min_bars = self.tr.ema_slow + 5

    def propose(self, symbol, tf, df, side=Side.LONG):
        close = df["close"]
        ef = float(ema(close, self.tr.ema_fast).iloc[-1])
        em = float(ema(close, self.tr.ema_mid).iloc[-1])
        es = float(ema(close, self.tr.ema_slow).iloc[-1])
        if any(pd.isna(x) for x in (ef, em, es)):
            return None
        price = float(close.iloc[-1])
        dist_pct = (price - em) / em * 100.0
        tol = self.tr.pullback_tolerance_pct + 0.5
        es_prev = float(ema(close, self.tr.ema_slow).iloc[-3]) if len(close) > 3 else es
        if side is Side.LONG:
            if not (ef > em > es and es >= es_prev and 0.0 <= dist_pct <= tol):
                return None
            lk = "ema_pullback"
        else:
            if not (ef < em < es and es <= es_prev and -tol <= dist_pct <= 0.0):
                return None
            lk = "ema_pullback_short"
        level = em
        if not self._limit_ok(df, level, side, self.tr.pullback_tolerance_pct + 1.0):
            return None
        target = self.cfg.target_for(tf) * self.tr.target_mult
        return StrategyProposal(
            strategy=self.name, side=side, level_price=level,
            level_kind=lk, strength=0.8,
            reasons=[f"ema {self.tr.ema_fast}/{self.tr.ema_mid}/{self.tr.ema_slow} stacked",
                     f"pullback {dist_pct:.2f}%"],
            target_pct=target, requires_macro=self.requires_macro,
            meta={"ema_fast": ef, "ema_mid": em, "ema_slow": es},
        )


# --------------------------------------------------------------------------
# 5) Volatility squeeze — low-bandwidth coil, then breakout retest
# --------------------------------------------------------------------------

class VolatilitySqueezeStrategy(Strategy):
    """Bollinger bandwidth compressing into a low-percentile coil precedes
    expansion. When a squeeze resolves with a close above the upper band, we
    park a limit at the breakout retest (just below the upper band). Catches
    the post-consolidation expansion the reaction strategy is too patient
    for."""

    name = "volatility_squeeze"
    requires_reference = False

    def __init__(self, cfg: StrategyConfig):
        super().__init__(cfg)
        self.sq = cfg.squeeze
        self.requires_macro = self.sq.require_macro
        self.min_bars = max(self.sq.lookback, self.sq.bb_period + 10)

    def propose(self, symbol, tf, df, side=Side.LONG):
        close = df["close"]
        lo, mid, up = bollinger(close, self.sq.bb_period, self.sq.bb_std)
        bw = ((up - lo) / mid.replace(0.0, float("nan"))).dropna()
        if len(bw) < self.sq.bb_period + 5:
            return None
        thresh = float(bw.tail(self.sq.lookback).quantile(self.sq.squeeze_quantile))
        if float(bw.iloc[-2]) > thresh:                    # prior bar not in a squeeze
            return None
        price = float(close.iloc[-1])
        target = self.cfg.target_for(tf) * self.sq.target_mult
        if side is Side.LONG:
            up_now = float(up.iloc[-1])
            if not price > up_now:
                return None
            level = up_now * (1 - self.sq.retest_band_pct / 100.0)
            reasons = [f"squeeze<=q{self.sq.squeeze_quantile}", f"break>{up_now:.6g}"]; lk = "squeeze_breakout"
        else:
            lo_now = float(lo.iloc[-1])
            if not price < lo_now:
                return None
            level = lo_now * (1 + self.sq.retest_band_pct / 100.0)
            reasons = [f"squeeze<=q{self.sq.squeeze_quantile}", f"break<{lo_now:.6g}"]; lk = "squeeze_breakdown"
        if not self._limit_ok(df, level, side, self.sq.retest_band_pct + 1.0):
            return None
        return StrategyProposal(
            strategy=self.name, side=side, level_price=level,
            level_kind=lk, strength=0.75, reasons=reasons,
            target_pct=target, requires_macro=self.requires_macro,
            meta={"squeeze_thresh": thresh},
        )


# --------------------------------------------------------------------------
# Registry
# --------------------------------------------------------------------------

#: name -> (class, toggle attribute on StrategyToggles)
class VwapReversionStrategy(Strategy):
    """Fade a stretch away from rolling VWAP. When price is pulled well below
    the volume-weighted average and starts turning back up, buy the snap to
    the mean. Counter-trend — no macro light required."""

    name = "vwap_reversion"
    requires_reference = False

    def __init__(self, cfg: StrategyConfig):
        super().__init__(cfg)
        self.requires_macro = False
        self.window = 30
        self.stretch_pct = 0.8
        self.min_bars = self.window + 6

    def propose(self, symbol, tf, df, side=Side.LONG):
        seg = df.tail(self.window)
        tp = (seg["high"] + seg["low"] + seg["close"]) / 3.0
        vol = seg["volume"].clip(lower=0.0)
        denom = float(vol.sum())
        if denom <= 0:
            return None
        vwap = float((tp * vol).sum() / denom)
        price = float(df["close"].iloc[-1])
        prev = float(df["close"].iloc[-2])
        dev = (price - vwap) / vwap * 100.0
        r = float(rsi(df["close"], self.cfg.filters.rsi_period).iloc[-1])
        if side is Side.LONG:
            if dev > -self.stretch_pct or price <= prev or r > self.cfg.filters.rsi_overbought:
                return None
            reasons = [f"{dev:.2f}% below VWAP", f"rsi={r:.0f}", "turning up"]; lk = "vwap_reversion"
        else:
            if dev < self.stretch_pct or price >= prev or r < self.cfg.filters.rsi_oversold:
                return None
            reasons = [f"+{dev:.2f}% above VWAP", f"rsi={r:.0f}", "turning down"]; lk = "vwap_reversion_short"
        level = price
        if not self._limit_ok(df, level, side, 2.0):
            return None
        return StrategyProposal(
            strategy=self.name, side=side, level_price=level,
            level_kind=lk, strength=min(1.0, abs(dev) / 3.0),
            reasons=reasons, target_pct=self.cfg.target_for(tf), requires_macro=False,
            meta={"vwap": vwap, "deviation_pct": dev},
        )


class LiquiditySweepStrategy(Strategy):
    """Stop-run reclaim. Price wicks below a recent swing low (sweeping the
    liquidity resting there) and then closes back above it — a classic trap
    reversal. Park a limit at the reclaimed level. Counter-trend."""

    name = "liquidity_sweep"
    requires_reference = False

    def __init__(self, cfg: StrategyConfig):
        super().__init__(cfg)
        self.requires_macro = False
        self.lookback = cfg.sims.extrema_window * 2 + 4
        self.min_bars = self.lookback + 4

    def propose(self, symbol, tf, df, side=Side.LONG):
        window = df.iloc[-(self.lookback + 2):-2]
        if len(window) < 5:
            return None
        price = float(df["close"].iloc[-1])
        if side is Side.LONG:
            swing = float(window["low"].min())
            if not (float(df["low"].iloc[-2]) < swing and price > swing):
                return None
            reasons = [f"swept low {swing:.6g}", "reclaimed up"]; lk = "sweep_reclaim"
        else:
            swing = float(window["high"].max())
            if not (float(df["high"].iloc[-2]) > swing and price < swing):
                return None
            reasons = [f"swept high {swing:.6g}", "reclaimed down"]; lk = "sweep_reclaim_short"
        level = swing
        if not self._limit_ok(df, level, side, 2.5):
            return None
        return StrategyProposal(
            strategy=self.name, side=side, level_price=level,
            level_kind=lk, strength=0.8, reasons=reasons,
            target_pct=self.cfg.target_for(tf), requires_macro=False,
            meta={"swing": swing},
        )


_STRATEGY_TABLE: list[tuple[str, type[Strategy], str]] = [
    ("reaction", ReactionStrategy, "reaction"),
    ("momentum_breakout", MomentumBreakoutStrategy, "momentum_breakout"),
    ("mean_reversion", MeanReversionStrategy, "mean_reversion"),
    ("trend_follow", TrendFollowStrategy, "trend_follow"),
    ("volatility_squeeze", VolatilitySqueezeStrategy, "volatility_squeeze"),
    ("vwap_reversion", VwapReversionStrategy, "vwap_reversion"),
    ("liquidity_sweep", LiquiditySweepStrategy, "liquidity_sweep"),
]

ALL_STRATEGY_NAMES = [name for name, _, _ in _STRATEGY_TABLE]


def build_strategies(cfg: StrategyConfig) -> list[Strategy]:
    """Instantiate every strategy enabled in ``cfg.strategies``."""
    out: list[Strategy] = []
    for name, klass, toggle in _STRATEGY_TABLE:
        if getattr(cfg.strategies, toggle, False):
            out.append(klass(cfg))
    return out


def get_strategy(cfg: StrategyConfig, name: str) -> Strategy:
    """Instantiate one strategy by name (used by the Track-2 spec generator)."""
    for n, klass, _ in _STRATEGY_TABLE:
        if n == name:
            return klass(cfg)
    raise KeyError(f"unknown strategy: {name!r} (have {ALL_STRATEGY_NAMES})")
