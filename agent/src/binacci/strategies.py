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

    # -- shared helper: clamp a long limit just below price within a band --
    def _long_limit_ok(self, df: pd.DataFrame, level: float, max_below_pct: float = 4.0) -> bool:
        price = float(df["close"].iloc[-1])
        return price * (1 - max_below_pct / 100.0) <= level <= price * 1.001


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
        if side is not Side.LONG:
            return None
        p = self.bk.donchian_period
        if len(df) < p + 2:
            return None
        close = df["close"]
        price = float(close.iloc[-1])
        # prior Donchian high EXCLUDING the current bar
        prior_high = float(df["high"].iloc[-(p + 1):-1].max())
        broke_out = price > prior_high
        if not broke_out:
            return None
        cmd_series = cmd(close, self.cfg.filters.cmd_fast, self.cfg.filters.cmd_slow)
        cmd_rising = float(cmd_series.iloc[-1]) > float(cmd_series.iloc[-2])
        vol = float(volume_ratio(df["volume"], self.cfg.filters.volume_lookback).iloc[-1])
        if not (cmd_rising and vol >= self.bk.volume_min_ratio):
            return None
        # retest limit: just below the broken level
        level = prior_high * (1 - self.bk.retest_band_pct / 100.0)
        if not self._long_limit_ok(df, level, max_below_pct=self.bk.retest_band_pct + 1.0):
            return None
        target = self.cfg.target_for(tf) * self.bk.target_mult
        return StrategyProposal(
            strategy=self.name, side=side, level_price=level,
            level_kind="donchian_retest", strength=min(1.0, vol / 2.0),
            reasons=[f"breakout>{prior_high:.6g}", f"cmd_rising", f"vol_x{vol:.2f}"],
            target_pct=target, requires_macro=self.requires_macro,
            meta={"prior_high": prior_high, "volume_ratio": vol},
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
        if side is not Side.LONG:
            return None
        close = df["close"]
        lo, mid, up = bollinger(close, self.mr.bb_period, self.mr.bb_std)
        lo_now = float(lo.iloc[-1])
        if pd.isna(lo_now):
            return None
        r = float(rsi(close, self.cfg.filters.rsi_period).iloc[-1])
        price = float(close.iloc[-1])
        prev_low = float(df["low"].iloc[-2])
        # evidence: recent pierce of the lower band + oversold RSI
        pierced = prev_low <= float(lo.iloc[-2]) if not pd.isna(lo.iloc[-2]) else False
        oversold = r <= self.mr.rsi_oversold
        if not (pierced and oversold):
            return None
        # reclaim: current close back at/above the lower band
        if self.mr.require_reclaim and price < lo_now:
            return None
        level = lo_now  # buy the retest of the band
        if not self._long_limit_ok(df, level, max_below_pct=3.0):
            return None
        target = self.cfg.target_for(tf) * self.mr.target_mult
        return StrategyProposal(
            strategy=self.name, side=side, level_price=level,
            level_kind="bb_lower_reclaim", strength=min(1.0, (self.mr.rsi_oversold - r + 10) / 30.0),
            reasons=[f"rsi={r:.1f}<={self.mr.rsi_oversold}", "bb_lower_pierce", "reclaim"],
            target_pct=target, requires_macro=self.requires_macro,
            meta={"rsi": r, "bb_lower": lo_now},
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
        if side is not Side.LONG:
            return None
        close = df["close"]
        ef = float(ema(close, self.tr.ema_fast).iloc[-1])
        em = float(ema(close, self.tr.ema_mid).iloc[-1])
        es = float(ema(close, self.tr.ema_slow).iloc[-1])
        if any(pd.isna(x) for x in (ef, em, es)):
            return None
        stacked = ef > em > es
        if not stacked:
            return None
        price = float(close.iloc[-1])
        # must be near (just above) the mid EMA — a pullback, not extended
        dist_pct = (price - em) / em * 100.0
        if not (0.0 <= dist_pct <= self.tr.pullback_tolerance_pct + 0.5):
            return None
        level = em  # limit at the mid EMA
        if not self._long_limit_ok(df, level, max_below_pct=self.tr.pullback_tolerance_pct + 1.0):
            return None
        slope = (es > float(ema(close, self.tr.ema_slow).iloc[-3])) if len(close) > 3 else True
        if not slope:
            return None
        target = self.cfg.target_for(tf) * self.tr.target_mult
        return StrategyProposal(
            strategy=self.name, side=side, level_price=level,
            level_kind="ema_pullback", strength=0.8,
            reasons=[f"ema{self.tr.ema_fast}>{self.tr.ema_mid}>{self.tr.ema_slow}",
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
        if side is not Side.LONG:
            return None
        close = df["close"]
        lo, mid, up = bollinger(close, self.sq.bb_period, self.sq.bb_std)
        bandwidth = (up - lo) / mid.replace(0.0, float("nan"))
        bw = bandwidth.dropna()
        if len(bw) < self.sq.bb_period + 5:
            return None
        window = bw.tail(self.sq.lookback)
        thresh = float(window.quantile(self.sq.squeeze_quantile))
        # was the PRIOR bar in a squeeze (low bandwidth)?
        prev_bw = float(bw.iloc[-2])
        in_squeeze = prev_bw <= thresh
        price = float(close.iloc[-1])
        up_now = float(up.iloc[-1])
        breakout = price > up_now
        if not (in_squeeze and breakout):
            return None
        level = up_now * (1 - self.sq.retest_band_pct / 100.0)
        if not self._long_limit_ok(df, level, max_below_pct=self.sq.retest_band_pct + 1.0):
            return None
        target = self.cfg.target_for(tf) * self.sq.target_mult
        return StrategyProposal(
            strategy=self.name, side=side, level_price=level,
            level_kind="squeeze_breakout", strength=0.75,
            reasons=[f"squeeze<=q{self.sq.squeeze_quantile}", f"break>{up_now:.6g}"],
            target_pct=target, requires_macro=self.requires_macro,
            meta={"bandwidth": prev_bw, "squeeze_thresh": thresh},
        )


# --------------------------------------------------------------------------
# Registry
# --------------------------------------------------------------------------

#: name -> (class, toggle attribute on StrategyToggles)
_STRATEGY_TABLE: list[tuple[str, type[Strategy], str]] = [
    ("reaction", ReactionStrategy, "reaction"),
    ("momentum_breakout", MomentumBreakoutStrategy, "momentum_breakout"),
    ("mean_reversion", MeanReversionStrategy, "mean_reversion"),
    ("trend_follow", TrendFollowStrategy, "trend_follow"),
    ("volatility_squeeze", VolatilitySqueezeStrategy, "volatility_squeeze"),
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
