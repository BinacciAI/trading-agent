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
from .fees import fee_model
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
    pnl_usd: float            # net of on-chain fees
    reason: str
    gross_pnl_usd: float = 0.0
    fees_usd: float = 0.0


class ExecutionEngine:
    """Owns all open positions and every risk rule."""

    def __init__(self, cfg: StrategyConfig, deposit_usd: float):
        self.cfg = cfg
        self.account = AccountState(deposit_usd=deposit_usd)
        self.positions: list[Position] = []
        self.closed: list[ClosedTrade] = []
        self.kill_switch_fired: bool = False
        import os as _os
        self.fees = fee_model()
        #: book realized P/L net of estimated on-chain fees (swap/perp/gas) even
        #: in paper, so the displayed edge is what a live wallet would actually
        #: keep. Disable with BINACCI_SIMULATE_FEES=false to see gross.
        self._simulate_fees = _os.environ.get("BINACCI_SIMULATE_FEES", "false").strip().lower() in ("1", "true", "yes", "on")
        #: Hard halt on NEW opens (preflight failure / boot-reconcile mismatch /
        #: unrecoverable venue desync). Closes and management still run so the
        #: book can always be flattened. Cleared by resume() after a human ack.
        self.trading_halted: bool = False
        self.halt_reason: str = ""

    def halt(self, reason: str) -> None:
        self.trading_halted = True
        self.halt_reason = reason

    def resume(self) -> None:
        self.trading_halted = False
        self.halt_reason = ""

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

    def can_open(self, symbol: str, tf: Timeframe, strategy: str = "reaction") -> bool:
        if self.kill_switch_fired:
            return False
        if self.trading_halted:
            return False
        if self.slots_free() <= 0:
            return False
        # per-book capacity: neither spot nor perps may hog the whole budget,
        # so both books stay live at the same time.
        market = self.cfg.market_for(strategy)
        cap = self.cfg.book_cap()
        in_book = sum(1 for p in self.positions
                      if p.state is not PositionState.CLOSED
                      and self.cfg.market_for(p.meta.get("strategy", "reaction")) == market)
        if in_book >= cap:
            return False
        # one position per (symbol, timeframe, strategy) — independent
        # strategies may each hold a position on the same market.
        for p in self.positions:
            if (p.symbol == symbol and p.timeframe == tf
                    and p.meta.get("strategy", "reaction") == strategy
                    and p.state is not PositionState.CLOSED):
                return False
        return True

    # ---------------- lifecycle ----------------

    def open_from_signal(self, sig: EntrySignal, fill_price: float, ts: datetime) -> Optional[Position]:
        strategy = getattr(sig, "strategy", "reaction")
        if not self.can_open(sig.symbol, sig.timeframe, strategy):
            return None
        size_mult = max(0.0, min(1.0, float(sig.meta.get("size_mult", 1.0) or 1.0)))
        notional = self.entry_notional_usd() * size_mult
        qty = notional / fill_price
        market = self.cfg.market_for(strategy)
        leverage = self.cfg.perps_leverage if market == "perp" else 1.0
        pos = Position(
            symbol=sig.symbol,
            timeframe=sig.timeframe,
            side=sig.side,
            state=PositionState.OPEN,
            target_pct=sig.target_pct,
            opened_ts=ts,
            meta={"level": sig.level_price, "strategy": strategy,
                  "gates": [g.step.value for g in sig.gates],
                  **dict(sig.meta or {}),
                  "market": market, "leverage": leverage},
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

        # catastrophic per-position stop — caps the tail loser so a handful
        # of averaged-down losers can't erase many small wins. Only relevant
        # once averaging is exhausted (the engine still tries to average at a
        # level first); fires only while the position never armed the trailing.
        hs = self.cfg.risk.hard_stop_pct
        if (hs and pos.stop_pct is None
                and pos.averaging_done >= len(self.cfg.margin.averaging_multipliers)
                and gain <= -hs):
            return self._close(pos, price, ts, reason="hard_stop")

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
        gross = pos.unrealized_pnl_usd(price)
        fees = 0.0
        if self._simulate_fees:
            market = self.cfg.market_for(pos.meta.get("strategy", "reaction"))
            lev = float(pos.meta.get("leverage", 1.0) or 1.0)
            hours = ((ts - pos.opened_ts).total_seconds() / 3600.0) if pos.opened_ts else 0.0
            fees = self.fees.position_roundtrip_usd(market, pos.notional_usd, lev, hours)
        pnl = gross - fees
        pos.fills.append(Fill(ts=ts, price=price, qty=-pos.qty, notional_usd=-pos.notional_usd, tag="exit"))
        pos.state = PositionState.CLOSED
        pos.closed_ts = ts
        pos.close_reason = reason
        pos.realized_pnl_usd = pnl
        pos.meta["fees_usd"] = round(fees, 4)
        self.account.realized_pnl_usd += pnl
        trade = ClosedTrade(position=pos, pnl_usd=pnl, reason=reason,
                            gross_pnl_usd=gross, fees_usd=fees)
        self.closed.append(trade)
        return trade

    # ---------------- venue reconciliation (keeps books == chain) ----------------

    def _entry_fill(self, pos: Position) -> Optional[Fill]:
        for f in pos.fills:
            if f.tag == "entry":
                return f
        return None

    def rollback_open(self, pos: Position) -> bool:
        """Remove a just-opened position that never filled on-chain. The engine
        booked it optimistically; the venue open failed, so it must not exist."""
        if pos in self.positions and pos.state is not PositionState.CLOSED:
            self.positions.remove(pos)
            return True
        return False

    def reconcile_open_fill(self, pos: Position, real_price: float) -> None:
        """Rewrite the entry fill to the venue's real fill price so avg_entry and
        all downstream P&L reflect what actually filled on-chain — not the limit
        level the engine booked at. USD notional spent is held constant."""
        if real_price <= 0:
            return
        f = self._entry_fill(pos)
        if f is None:
            return
        pos.meta["booked_entry_price"] = f.price
        f.price = real_price
        f.qty = f.notional_usd / real_price
        pos.meta["reconciled_entry"] = True

    def reconcile_average_fill(self, pos: Position, real_price: float) -> None:
        """Rewrite the most recent averaging add to its real on-chain fill."""
        if real_price <= 0 or not pos.fills:
            return
        f = pos.fills[-1]
        if not f.tag.startswith("avg"):
            return
        f.price = real_price
        f.qty = f.notional_usd / real_price

    def rollback_average(self, pos: Position) -> bool:
        """Undo the most recent averaging add when the venue add failed."""
        if pos.fills and pos.fills[-1].tag.startswith("avg"):
            pos.fills.pop()
            pos.averaging_done = max(0, pos.averaging_done - 1)
            return True
        return False

    def reconcile_close_fill(self, trade: ClosedTrade, real_price: float) -> None:
        """Recompute realized P&L from the venue's real exit fill price."""
        if real_price <= 0:
            return
        pos = trade.position
        exit_fill = pos.fills[-1] if pos.fills and pos.fills[-1].tag == "exit" else None
        old_pnl = pos.realized_pnl_usd
        new_pnl = pos.unrealized_pnl_usd(real_price)  # open size, exits excluded
        if exit_fill is not None:
            exit_fill.price = real_price
        self.account.realized_pnl_usd += (new_pnl - old_pnl)
        pos.realized_pnl_usd = new_pnl
        trade.pnl_usd = new_pnl
        pos.meta["reconciled_close"] = True

    def revert_close(self, trade: ClosedTrade) -> Optional[Position]:
        """Un-close a position whose on-chain close failed after retries, so the
        engine's books match the chain (the position is still open on-chain).
        It returns to management; the caller should halt new opens + alert."""
        pos = trade.position
        if pos.state is not PositionState.CLOSED:
            return pos
        if pos.fills and pos.fills[-1].tag == "exit":
            pos.fills.pop()
        self.account.realized_pnl_usd -= pos.realized_pnl_usd
        pos.realized_pnl_usd = 0.0
        pos.closed_ts = None
        prior = trade.reason
        pos.close_reason = ""
        pos.state = (PositionState.SL_IN_PROFIT if pos.stop_pct is not None
                     else PositionState.OPEN)
        if trade in self.closed:
            self.closed.remove(trade)
        pos.meta["close_failed"] = prior
        pos.meta["close_attempts"] = pos.meta.get("close_attempts", 0) + 1
        return pos

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
        # close worst-first: if the venue can only process closes sequentially,
        # the biggest losers get flattened before slower ones can bleed further.
        openpos = [p for p in self.positions
                   if p.state in (PositionState.OPEN, PositionState.SL_IN_PROFIT)]
        openpos.sort(key=lambda p: p.unrealized_pnl_usd(prices.get(p.symbol, p.avg_entry)))
        for p in openpos:
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
            "trading_halted": self.trading_halted,
            "halt_reason": self.halt_reason,
            "closed_trades": len(self.closed),
        }


# end of module
