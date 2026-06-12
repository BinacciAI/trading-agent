"""Execution engine — margin, averaging, slots, trailing SL, kill switch.

Deterministic. No AI in this layer, by design:

* 30/70 margin model: 30% of the deposit is reserved, never touched.
  Entry = 0.5% of working margin = 0.35% of deposit.
* Averaging x4 then x2, only AT a level (never panic): one fully averaged
  position caps at ~3% of deposit.
* Max 5 simultaneous positions, with smart slot return — a position whose
  trailing SL is already in profit will close green either way, so it
  releases its slot.
* Stepped trailing SL: trigger +0.4% -> SL +0.2%, then +0.1% steps. A
  position almost cannot close in the red.
* Hard stop-cock: if aggregate floating drawdown reaches 30% of the
  deposit, EVERYTHING closes. Combined with the 30% reserve this is a
  double safety margin.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from .config import StrategyConfig, Timeframe
from .models import (
    EntrySignal,
    Fill,
    Position,
    PositionState,
    Side,
)


@dataclass(slots=True)
class AccountState:
    deposit_usd: float
    realized_pnl_usd: float = 0.0

    @property
    def equity_usd(self) -> float:
        return self.deposit_usd + self.realized_pnl_usd


@dataclass
class ClosedTrade:
    position: Position
    pnl_usd: float
    reason: str


class ExecutionEngine:
    """Owns all open positions and every risk rule."""

    def __init__(self, cfg: StrategyConfig, deposit_usd: float):
        self.cfg = cfg
        self.account = AccountState(deposit_usd=deposit_usd)
        self.positions: list[Position] = []
        self.closed: list[ClosedTrade] = []
        self.kill_switch_fired: bool = False

    # ---------------- sizing ----------------

    def entry_notional_usd(self) -> float:
        return self.account.deposit_usd * self.cfg.margin.entry_pct_of_deposit

    def averaging_notional_usd(self, pos: Position) -> Optional[float]:
        """Notional to ADD for the next averaging step, or None if done."""
        mults = self.cfg.margin.averaging_multipliers
        if pos.averaging_done >= len(mults):
            return None
        target_mult = 1.0
        for m in mults[: pos.averaging_done + 1]:
            target_mult *= m
        base = self.account.deposit_usd * self.cfg.margin.entry_pct_of_deposit
        target_notional = base * target_mult
        return max(target_notional - pos.notional_usd, 0.0)

    # ---------------- slots ----------------

    def used_slots(self) -> int:
        n = 0
        for p in self.positions:
            if p.state in (PositionState.PENDING, PositionState.OPEN):
                n += 1
            elif p.state is PositionState.SL_IN_PROFIT and not self.cfg.risk.sl_in_profit_releases_slot:
                n += 1
        return n

    def slots_free(self) -> int:
        return max(self.cfg.risk.max_positions - self.used_slots(), 0)

    def can_open(self, symbol: str, tf: Timeframe) -> bool:
        if self.kill_switch_fired:
            return False
        if self.slots_free() <= 0:
            return False
        # one position per (symbol, timeframe)
        for p in self.positions:
            if p.symbol == symbol and p.timeframe == tf and p.state is not PositionState.CLOSED:
                return False
        return True

    # ---------------- lifecycle ----------------

    def open_from_signal(self, sig: EntrySignal, fill_price: float, ts: datetime) -> Optional[Position]:
        if not self.can_open(sig.symbol, sig.timeframe):
            return None
        notional = self.entry_notional_usd()
        qty = notional / fill_price
        pos = Position(
            symbol=sig.symbol,
            timeframe=sig.timeframe,
            side=sig.side,
            state=PositionState.OPEN,
            target_pct=sig.target_pct,
            opened_ts=ts,
            meta={"level": sig.level_price, "gates": [g.step.value for g in sig.gates]},
        )
        pos.fills.append(Fill(ts=ts, price=fill_price, qty=qty, notional_usd=notional, tag="entry"))
        self.positions.append(pos)
        return pos

    def try_average(self, pos: Position, level_price: float, fill_price: float, ts: datetime) -> bool:
        """Average ONLY at a level and only while the position is in
        drawdown (the market gave a better point)."""
        if pos.state is not PositionState.OPEN:
            return False
        if pos.gain_pct(fill_price) >= 0:
            return False
        add = self.averaging_notional_usd(pos)
        if add is None or add <= 0:
            return False
        qty = add / fill_price
        pos.averaging_done += 1
        pos.fills.append(
            Fill(ts=ts, price=fill_price, qty=qty, notional_usd=add,
                 tag=f"avg{pos.averaging_done}")
        )
        pos.meta[f"avg{pos.averaging_done}_level"] = level_price
        return True

    # ---------------- per-tick management ----------------

    def on_price(self, pos: Position, price: float, ts: datetime) -> Optional[ClosedTrade]:
        """Update trailing SL / take profit for one position. Returns the
        closed trade if it exited on this tick."""
        if pos.state not in (PositionState.OPEN, PositionState.SL_IN_PROFIT):
            return None

        gain = pos.gain_pct(price)
        pos.peak_gain_pct = max(pos.peak_gain_pct, gain)

        # take profit (short, guaranteed piece — we catch the reaction)
        if gain >= pos.target_pct:
            return self._close(pos, price, ts, reason="take_profit")

        # trailing ladder
        stop = self.cfg.trailing.stop_for(pos.peak_gain_pct)
        if stop is not None:
            pos.stop_pct = stop
            if pos.state is PositionState.OPEN:
                pos.state = PositionState.SL_IN_PROFIT  # slot released
            if gain <= stop + 1e-9:
                return self._close(pos, price, ts, reason="trailing_stop")
        return None

    def _close(self, pos: Position, price: float, ts: datetime, reason: str) -> ClosedTrade:
        pnl = pos.unrealized_pnl_usd(price)
        pos.fills.append(Fill(ts=ts, price=price, qty=-pos.qty, notional_usd=-pos.notional_usd, tag="exit"))
        pos.state = PositionState.CLOSED
        pos.closed_ts = ts
        pos.close_reason = reason
        pos.realized_pnl_usd = pnl
        self.account.realized_pnl_usd += pnl
        trade = ClosedTrade(position=pos, pnl_usd=pnl, reason=reason)
        self.closed.append(trade)
        return trade

    # ---------------- kill switch ----------------

    def aggregate_drawdown_usd(self, prices: dict[str, float]) -> float:
        dd = 0.0
        for p in self.positions:
            if p.state in (PositionState.OPEN, PositionState.SL_IN_PROFIT):
                px = prices.get(p.symbol)
                if px is None:
                    continue
                pnl = p.unrealized_pnl_usd(px)
                if pnl < 0:
                    dd += -pnl
        return dd

    def check_kill_switch(self, prices: dict[str, float], ts: datetime) -> list[ClosedTrade]:
        """If aggregate floating drawdown >= 30% of deposit, close ALL."""
        limit = self.account.deposit_usd * self.cfg.risk.max_aggregate_drawdown_pct
        if self.aggregate_drawdown_usd(prices) < limit:
            return []
        self.kill_switch_fired = True
        out: list[ClosedTrade] = []
        for p in list(self.positions):
            if p.state in (PositionState.OPEN, PositionState.SL_IN_PROFIT):
                px = prices.get(p.symbol, p.avg_entry)
                out.append(self._close(p, px, ts, reason="kill_switch"))
        return out

    # ---------------- reporting ----------------

    def open_positions(self) -> list[Position]:
        return [p for p in self.positions
                if p.state in (PositionState.OPEN, PositionState.SL_IN_PROFIT)]

    def snapshot(self, prices: dict[str, float]) -> dict:
        open_pos = self.open_positions()
        unreal = sum(p.unrealized_pnl_usd(prices.get(p.symbol, p.avg_entry)) for p in open_pos)
        return {
            "deposit_usd": self.account.deposit_usd,
            "realized_pnl_usd": round(self.account.realized_pnl_usd, 2),
            "unrealized_pnl_usd": round(unreal, 2),
            "equity_usd": round(self.account.equity_usd + unreal, 2),
            "open_positions": len(open_pos),
            "slots_used": self.used_slots(),
            "slots_max": self.cfg.risk.max_positions,
            "aggregate_drawdown_usd": round(self.aggregate_drawdown_usd(prices), 2),
            "kill_switch_fired": self.kill_switch_fired,
            "closed_trades": len(self.closed),
        }


# end of module
