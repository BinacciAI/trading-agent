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
    Side,
)
from .simulations import (
    ReferenceBook,
    Sim01ColdStart,
    Sim02ReferenceUpdate,
    Sim03CleanReference,
    SimAEntryZone,
    SimBEntryLevel,
)


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
    ):
        self.cfg = cfg
        self.engine = engine
        self.macro_provider = macro_provider or (lambda: None)
        self.book = ReferenceBook()
        self.sim01 = Sim01ColdStart(cfg.sims)
        self.sim02 = Sim02ReferenceUpdate(cfg.sims)
        self.sim03 = Sim03CleanReference(cfg.sims, cfg.filters)
        self.simA = SimAEntryZone(cfg.sims, cfg.filters)
        self.simB = SimBEntryLevel(cfg.sims)
        self.pending: list[PendingEntry] = []
        self.traces: list[DecisionTrace] = []
        self.max_traces = 500
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
        """Run gates 01-04; on success, park a pending limit at the SimB
        level (gate 05 completes on touch via :meth:`on_candle`)."""
        trace = DecisionTrace(symbol=symbol, timeframe=tf, ts=ts)
        side = Side.LONG  # spot default; perps venue may evaluate shorts too

        # 01 — fresh reference
        ref = self.book.get(symbol, tf)
        max_age = timedelta(minutes=tf.minutes * (self.cfg.sims.extrema_window * 6))
        fresh = ref is not None and (ts - ref.ts) <= max_age
        if not trace.add(GateStep.REFERENCE, fresh,
                         f"ref={ref.kind.value}@{ref.price:.6g}" if ref else "no reference"):
            self._record(trace)
            return trace

        # 02 — entry zone
        zone = self.simA.assess(df, side)
        if not trace.add(GateStep.ZONE, zone.in_zone, ",".join(zone.reasons) or "not in zone"):
            self._record(trace)
            return trace

        # 03 — filters
        if not trace.add(GateStep.FILTERS, zone.filters_ok, str(zone.filter_detail)):
            self._record(trace)
            return trace

        # 04 — macro
        verdict: MacroVerdict = evaluate_macro(self.macro_provider(), self.cfg.macro, side)
        if not trace.add(GateStep.MACRO, verdict.ok, verdict.detail):
            self._record(trace)
            return trace

        # 05 — find the level; entry completes on touch
        level = self.simB.pick(df, side)
        if level is None:
            trace.add(GateStep.LEVEL, False, "no tradable level near price")
            self._record(trace)
            return trace

        if not self.engine.can_open(symbol, tf):
            trace.add(GateStep.LEVEL, False, "slots full or duplicate position")
            self._record(trace)
            return trace

        sig = EntrySignal(
            symbol=symbol, timeframe=tf, side=side,
            level_price=level.price, reference=ref, gates=list(trace.gates),
            ts=ts, target_pct=self.cfg.target_for(tf),
            meta={"level_kind": level.kind, "level_strength": level.strength},
        )
        # replace any stale pending for same (symbol, tf)
        self.pending = [p for p in self.pending
                        if not (p.signal.symbol == symbol and p.signal.timeframe == tf)]
        ttl = timedelta(minutes=tf.minutes * 8)
        self.pending.append(PendingEntry(signal=sig, created=ts, expires=ts + ttl))
        trace.add(GateStep.LEVEL, True,
                  f"limit parked @ {level.price:.6g} ({level.kind})")
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
