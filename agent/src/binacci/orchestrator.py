"""Orchestrator — wires the 5-step entry chain to the execution engine.

Step 01  Fresh reference   (Sim01/02/03 -> ReferenceBook)
Step 02  Entry zone        (SimA: fib zone / divergence / BB)
Step 03  Filters OK        (CMD, BB, volume, RSI confirm the reaction)
Step 04  Macro gate        (totalCap + BTC.D + USDT.D)
Step 05  Level touch       (SimB level; limit fill on touch)

No confirmation at any step -> no entry. The AI layer may *explain* what
the bot did; it cannot alter any step.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable, Optional

import pandas as pd

from .config import StrategyConfig, Timeframe
from .execution import ClosedTrade, ExecutionEngine
from .macro import MacroSnapshot, MacroVerdict, evaluate_macro
from .models import (
    Candle,
    EntrySignal,
    GateResult,
    GateStep,
    Position,
    RefKind,
    ReferencePoint,
    Side,
)
from .simulations import (
    ReferenceBook,
    Sim01ColdStart,
    Sim02ReferenceUpdate,
    Sim03CleanReference,
)
from .strategies import Strategy, build_strategies


@dataclass
class PendingEntry:
    """A SimB level we are watching for a touch (resting limit order)."""

    signal: EntrySignal
    created: datetime
    expires: datetime


@dataclass
class DecisionTrace:
    """Full audit of one evaluation — what passed, what blocked."""

    symbol: str
    timeframe: Timeframe
    ts: datetime
    strategy: str = "reaction"
    gates: list[GateResult] = field(default_factory=list)
    entered: bool = False

    def add(self, step: GateStep, passed: bool, detail: str = "") -> bool:
        self.gates.append(GateResult(step=step, passed=passed, detail=detail))
        return passed


class Orchestrator:
    def __init__(
        self,
        cfg: StrategyConfig,
        engine: ExecutionEngine,
        macro_provider: Optional[Callable[[], Optional[MacroSnapshot]]] = None,
        strategies: Optional[list[Strategy]] = None,
    ):
        self.cfg = cfg
        self.engine = engine
        self.macro_provider = macro_provider or (lambda: None)
        self.book = ReferenceBook()
        self.sim01 = Sim01ColdStart(cfg.sims)
        self.sim02 = Sim02ReferenceUpdate(cfg.sims)
        self.sim03 = Sim03CleanReference(cfg.sims, cfg.filters)
        #: The active strategy portfolio. Defaults to every strategy enabled
        #: in cfg.strategies; the core reaction strategy is always first.
        self.strategies: list[Strategy] = strategies or build_strategies(cfg)
        self.pending: list[PendingEntry] = []
        self.traces: list[DecisionTrace] = []
        self.max_traces = 800
        #: Venue execution hooks (set by the live loop). Called AFTER the
        #: deterministic engine has accepted the open/close — the venue
        #: mirrors engine state on-chain; it never decides.
        self.on_open = None   # fn(position) -> None
        self.on_close = None  # fn(closed_trade) -> None

    # ---------------- background sims ----------------

    def cold_start(self, symbol: str, tf: Timeframe, history: pd.DataFrame) -> None:
        self.sim01.run(symbol, tf, history, self.book)

    def update_references(self, symbol: str, tf: Timeframe, df: pd.DataFrame) -> None:
        self.sim02.step(symbol, tf, df, self.book)
        self.sim03.step(symbol, tf, df, self.book)

    # ---------------- evaluation ----------------

    def evaluate(self, symbol: str, tf: Timeframe, df: pd.DataFrame, ts: datetime) -> DecisionTrace:
        """Run every active strategy over this (symbol, timeframe). Each is
        an independent 5-gate evaluation that, on success, parks a pending
        limit (gate 05 completes on touch via :meth:`on_candle`). Strategies
        are isolated: one strategy's block never affects another's entry."""
        # Shared reference state (only gates strategies that require it).
        ref = self.book.get(symbol, tf)
        max_age = timedelta(minutes=tf.minutes * (self.cfg.sims.extrema_window * 6))
        fresh = ref is not None and (ts - ref.ts) <= max_age

        last_trace: Optional[DecisionTrace] = None
        for strat in self.strategies:
            if len(df) < strat.min_bars:
                continue
            # Spot strategies are long-only; perps strategies trade both ways
            # (when shorts are enabled). Both books run at the same time.
            if self.cfg.market_for(strat.name) == "perp" and self.cfg.allow_shorts:
                sides = [Side.LONG, Side.SHORT]
            else:
                sides = [Side.LONG]
            for s in sides:
                tr = self._evaluate_one(strat, symbol, tf, df, ts, s, ref, fresh)
                last_trace = tr
                # if this strategy parked an entry, don't also try the other side
                if tr.gates and tr.gates[-1].step is GateStep.LEVEL and tr.gates[-1].passed:
                    break
        return last_trace or DecisionTrace(symbol=symbol, timeframe=tf, ts=ts)

    def _evaluate_one(self, strat: Strategy, symbol: str, tf: Timeframe,
                      df: pd.DataFrame, ts: datetime, side: Side,
                      ref: Optional[ReferencePoint], fresh: bool) -> DecisionTrace:
        trace = DecisionTrace(symbol=symbol, timeframe=tf, ts=ts, strategy=strat.name)

        # 01 — fresh reference (only strategies that anchor on one)
        if strat.requires_reference:
            if not trace.add(GateStep.REFERENCE, fresh,
                             f"ref={ref.kind.value}@{ref.price:.6g}" if ref else "no reference"):
                self._record(trace)
                return trace
        else:
            trace.add(GateStep.REFERENCE, True, "reference not required")

        # 02/03 — zone + filters (the strategy's own setup logic)
        proposal = strat.propose(symbol, tf, df, side)
        if proposal is None:
            trace.add(GateStep.ZONE, False, "no setup")
            self._record(trace)
            return trace
        trace.add(GateStep.ZONE, True, ",".join(proposal.reasons) or "in zone")
        trace.add(GateStep.FILTERS, True, str(proposal.meta.get("filters", "")) or "confirmed")

        # 04 — macro (per-strategy: some are explicit counter-trend fades)
        if proposal.requires_macro:
            verdict: MacroVerdict = evaluate_macro(self.macro_provider(), self.cfg.macro, side)
            if not trace.add(GateStep.MACRO, verdict.ok, verdict.detail):
                self._record(trace)
                return trace
        else:
            trace.add(GateStep.MACRO, True, "macro gate not required for this strategy")

        # 05 — level touch; slot + duplicate check is per-strategy
        if not self.engine.can_open(symbol, tf, strat.name):
            trace.add(GateStep.LEVEL, False, "slots full or duplicate position")
            self._record(trace)
            return trace

        reference = ref if ref is not None else ReferencePoint(
            symbol=symbol, timeframe=tf, kind=RefKind.LOCAL_MIN,
            price=proposal.level_price, ts=ts,
            meta={"synthetic": True, "strategy": strat.name},
        )
        target = proposal.target_pct if proposal.target_pct is not None else self.cfg.target_for(tf)
        # PERPS aim for a larger price move before TP (spot is untouched). This
        # is the one place a target becomes a signal, so it covers all perp
        # strategies uniformly — including the ones with no per-strategy mult.
        if self.cfg.market_for(strat.name) == "perp":
            target *= self.cfg.perps_target_mult
        sig = EntrySignal(
            symbol=symbol, timeframe=tf, side=side,
            level_price=proposal.level_price, reference=reference,
            gates=list(trace.gates), ts=ts, target_pct=target,
            strategy=strat.name,
            meta={"level_kind": proposal.level_kind,
                  "level_strength": proposal.strength,
                  "strategy": strat.name, "reasons": proposal.reasons,
                  "market": self.cfg.market_for(strat.name)},
        )
        # replace any stale pending for same (symbol, tf, strategy)
        self.pending = [p for p in self.pending
                        if not (p.signal.symbol == symbol and p.signal.timeframe == tf
                                and p.signal.strategy == strat.name)]
        ttl = timedelta(minutes=tf.minutes * 8)
        self.pending.append(PendingEntry(signal=sig, created=ts, expires=ts + ttl))
        trace.add(GateStep.LEVEL, True,
                  f"limit parked @ {proposal.level_price:.6g} ({proposal.level_kind})")
        self._record(trace)
        return trace

    # ---------------- candle stream ----------------

    def on_candle(self, symbol: str, tf: Timeframe, candle: Candle,
                  prices: dict[str, float]) -> list[ClosedTrade]:
        """Advance state machine on one candle: pending fills, averaging,
        trailing, take profit, kill switch."""
        ts = candle.ts
        closed: list[ClosedTrade] = []

        # expire stale pendings
        self.pending = [p for p in self.pending if p.expires > ts]

        # pending limit fills (gate 05: level touch)
        for p in list(self.pending):
            sig = p.signal
            if sig.symbol != symbol or sig.timeframe != tf:
                continue
            tol = self.cfg.sims.level_tolerance_pct
            touched = (candle.low <= sig.level_price * (1 + tol / 100)
                       if sig.side is Side.LONG
                       else candle.high >= sig.level_price * (1 - tol / 100))
            if touched:
                pos = self.engine.open_from_signal(sig, fill_price=sig.level_price, ts=ts)
                self.pending.remove(p)
                if pos is not None:
                    if self.traces:
                        self.traces[-1].entered = True
                    if self.on_open:
                        try:
                            self.on_open(pos)
                        except Exception:  # venue failure never corrupts engine state
                            import logging
                            logging.getLogger(__name__).exception("on_open hook failed")

        # manage open positions on this symbol
        for pos in self.engine.open_positions():
            if pos.symbol != symbol:
                continue
            # averaging at a better level (only while in drawdown)
            if pos.timeframe == tf and pos.averaging_done < len(self.cfg.margin.averaging_multipliers):
                if pos.gain_pct(candle.close) < 0:
                    # next level below current avg entry
                    lvl = None
                    df_unavailable = True  # SimB rerun handled in evaluate cycle; use entry level ladder
                    base_level = pos.meta.get("level", pos.avg_entry)
                    drop_steps = (1.0, 2.0)  # % below last fill where averaging may trigger
                    step = drop_steps[min(pos.averaging_done, len(drop_steps) - 1)]
                    trigger_price = pos.fills[-1].price * (1 - step / 100.0) if pos.side is Side.LONG \
                        else pos.fills[-1].price * (1 + step / 100.0)
                    hit = candle.low <= trigger_price if pos.side is Side.LONG else candle.high >= trigger_price
                    if hit:
                        self.engine.try_average(pos, level_price=trigger_price,
                                                fill_price=trigger_price, ts=ts)
            trade = self.engine.on_price(pos, candle.close, ts)
            if trade:
                closed.append(trade)

        # kill switch across the whole book
        closed += self.engine.check_kill_switch(prices, ts)

        if self.on_close:
            for trade in closed:
                try:
                    self.on_close(trade)
                except Exception:
                    import logging
                    logging.getLogger(__name__).exception("on_close hook failed")
        return closed

    # ---------------- misc ----------------

    def _record(self, trace: DecisionTrace) -> None:
        self.traces.append(trace)
        if len(self.traces) > self.max_traces:
            self.traces = self.traces[-self.max_traces:]
