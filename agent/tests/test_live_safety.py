"""Live-funds safety: rollback/reconcile/halt + receipt confirmation + the
venue hook integration that keeps the engine's books == the chain.

These cover the five go-live blockers and two of the risk items:
  1. rollback on venue failure (open) / revert+halt (close)
  2. P&L reconciled to the real on-chain fill, not the booked limit price
  3. on-chain receipt verification (confirmed / reverted / unconfirmed)
  4. preflight gate halts new opens
  5. boot reconcile halts on unverified restored positions
  + worst-first kill switch ordering
"""

from datetime import datetime, timezone

import pytest

from binacci.config import RuntimeConfig, StrategyConfig, Timeframe
from binacci.execution import ExecutionEngine
from binacci.models import EntrySignal, PositionState, ReferencePoint, RefKind, Side
from binacci.orchestrator import Orchestrator
from binacci.live import LiveLoop
from binacci.venues import OrderResult, confirm_receipt_via_rpc
import binacci.venues as venues


def _ts():
    return datetime.now(timezone.utc)


def _signal(symbol="BNB", tf=Timeframe.M15, level=100.0, target=0.5):
    ref = ReferencePoint(symbol=symbol, timeframe=tf, kind=RefKind.LOCAL_MIN,
                         price=level * 0.99, ts=_ts())
    return EntrySignal(symbol=symbol, timeframe=tf, side=Side.LONG,
                       level_price=level, reference=ref, gates=[], ts=_ts(),
                       target_pct=target)


@pytest.fixture
def engine():
    return ExecutionEngine(StrategyConfig(), deposit_usd=10_000.0)


# --------------------------------------------------------------------------
# Blocker 1 + 2 — engine reconciliation primitives
# --------------------------------------------------------------------------

def test_rollback_open_removes_phantom(engine):
    pos = engine.open_from_signal(_signal(), fill_price=100.0, ts=_ts())
    assert pos in engine.positions
    assert engine.rollback_open(pos) is True
    assert pos not in engine.positions
    # idempotent — a second rollback is a no-op
    assert engine.rollback_open(pos) is False


def test_reconcile_open_fill_uses_real_price(engine):
    pos = engine.open_from_signal(_signal(level=100.0), fill_price=100.0, ts=_ts())
    booked_notional = pos.notional_usd
    # the chain actually filled at 101.5 (slippage)
    engine.reconcile_open_fill(pos, 101.5)
    assert pos.avg_entry == pytest.approx(101.5)
    # USD spent is unchanged; only qty/price move
    assert pos.notional_usd == pytest.approx(booked_notional)
    assert pos.meta["booked_entry_price"] == pytest.approx(100.0)
    assert pos.meta["reconciled_entry"] is True


def test_reconcile_and_rollback_average(engine):
    pos = engine.open_from_signal(_signal(), fill_price=100.0, ts=_ts())
    assert engine.try_average(pos, 99.0, 99.0, _ts())
    assert pos.averaging_done == 1
    # reconcile the add to its real fill
    engine.reconcile_average_fill(pos, 98.0)
    assert pos.fills[-1].price == pytest.approx(98.0)
    # rollback the add (venue add failed)
    assert engine.rollback_average(pos) is True
    assert pos.averaging_done == 0
    assert all(not f.tag.startswith("avg") for f in pos.fills)


def test_reconcile_close_fill_adjusts_pnl_and_account(engine):
    pos = engine.open_from_signal(_signal(level=100.0), fill_price=100.0, ts=_ts())
    trade = engine._close(pos, 105.0, _ts(), reason="take_profit")
    booked_pnl = trade.pnl_usd
    acct_after_book = engine.account.realized_pnl_usd
    assert acct_after_book == pytest.approx(booked_pnl)
    # real exit actually filled at 104.0 (worse than booked)
    engine.reconcile_close_fill(trade, 104.0)
    assert trade.pnl_usd < booked_pnl
    # account moved by exactly the delta
    assert engine.account.realized_pnl_usd == pytest.approx(trade.pnl_usd)
    assert pos.meta["reconciled_close"] is True


def test_revert_close_reopens_and_restores_account(engine):
    pos = engine.open_from_signal(_signal(level=100.0), fill_price=100.0, ts=_ts())
    trade = engine._close(pos, 105.0, _ts(), reason="take_profit")
    assert pos.state is PositionState.CLOSED
    assert trade in engine.closed
    booked_pnl = trade.pnl_usd
    engine.revert_close(trade)
    # position is managed again, books match a still-open chain position
    assert pos.state in (PositionState.OPEN, PositionState.SL_IN_PROFIT)
    assert trade not in engine.closed
    assert engine.account.realized_pnl_usd == pytest.approx(0.0)
    assert pos.realized_pnl_usd == pytest.approx(0.0)
    assert pos.meta["close_failed"] == "take_profit"
    assert pos.meta["close_attempts"] == 1
    # the exit fill was removed -> position size intact
    assert all(f.tag != "exit" for f in pos.fills)
    assert booked_pnl != 0.0


# --------------------------------------------------------------------------
# Blocker 4 — halt gate
# --------------------------------------------------------------------------

def test_halt_blocks_opens_then_resume(engine):
    assert engine.can_open("BNB", Timeframe.M15) is True
    engine.halt("preflight failed: twak not installed")
    assert engine.can_open("BNB", Timeframe.M15) is False
    assert engine.open_from_signal(_signal(), fill_price=100.0, ts=_ts()) is None
    engine.resume()
    assert engine.can_open("BNB", Timeframe.M15) is True


# --------------------------------------------------------------------------
# Risk — worst-first kill switch ordering
# --------------------------------------------------------------------------

def test_kill_switch_closes_worst_first():
    cfg = StrategyConfig()
    cfg.book_share = 1.0
    cfg.risk.max_aggregate_drawdown_pct = 0.0001  # ensure the switch fires
    eng = ExecutionEngine(cfg, deposit_usd=1000.0)
    # three positions with different drawdowns at the same notional
    for sym in ("AAA", "BBB", "CCC"):
        eng.open_from_signal(_signal(symbol=sym, level=100.0), fill_price=100.0, ts=_ts())
    # AAA worst (-40%), CCC mildest (-20%)
    prices = {"AAA": 60.0, "BBB": 70.0, "CCC": 80.0}
    closed = eng.check_kill_switch(prices, _ts())
    assert eng.kill_switch_fired
    assert [t.position.symbol for t in closed] == ["AAA", "BBB", "CCC"]  # worst first
    assert len(closed) == 3


# --------------------------------------------------------------------------
# Blocker 3 — on-chain receipt verification (mocked RPC)
# --------------------------------------------------------------------------

class _FakeResp:
    def __init__(self, payload):
        import json
        self._b = json.dumps(payload).encode()

    def read(self):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_confirm_receipt_confirmed(monkeypatch):
    monkeypatch.setattr(venues.urllib.request, "urlopen",
                        lambda *a, **k: _FakeResp({"result": {"status": "0x1"}}))
    assert confirm_receipt_via_rpc("0xabc", "http://rpc", timeout_s=2, poll_s=0.1) == "confirmed"


def test_confirm_receipt_reverted(monkeypatch):
    monkeypatch.setattr(venues.urllib.request, "urlopen",
                        lambda *a, **k: _FakeResp({"result": {"status": "0x0"}}))
    assert confirm_receipt_via_rpc("0xabc", "http://rpc", timeout_s=2, poll_s=0.1) == "reverted"


def test_confirm_receipt_unconfirmed(monkeypatch):
    # result null forever -> times out as unconfirmed
    monkeypatch.setattr(venues.urllib.request, "urlopen",
                        lambda *a, **k: _FakeResp({"result": None}))
    assert confirm_receipt_via_rpc("0xabc", "http://rpc", timeout_s=1, poll_s=0.1) == "unconfirmed"


def test_confirm_receipt_no_hash_is_unconfirmed():
    assert confirm_receipt_via_rpc("", "http://rpc") == "unconfirmed"


# --------------------------------------------------------------------------
# Blocker 1/2 — venue hook integration with a fake venue
# --------------------------------------------------------------------------

class FakeVenue:
    """Deterministic stand-in for a real on-chain venue."""
    name = "fake"

    def __init__(self, ok=True, fill_price=0.0, status="confirmed"):
        self.ok = ok
        self.fill_price = fill_price
        self.status = status
        self.opens = 0
        self.closes = 0

    def place_limit(self, symbol, side, price, notional_usd):
        self.opens += 1
        return OrderResult(ok=self.ok, venue=self.name,
                           tx_or_id="0xopen" if self.ok else "",
                           fill_price=self.fill_price, status=self.status,
                           confirmed=self.status == "confirmed",
                           detail="" if self.ok else "boom")

    def market_close(self, symbol, side, notional_usd):
        self.closes += 1
        return OrderResult(ok=self.ok, venue=self.name,
                           tx_or_id="0xclose" if self.ok else "",
                           fill_price=self.fill_price, status=self.status,
                           confirmed=self.status == "confirmed",
                           detail="" if self.ok else "boom")

    def snapshot_onchain(self):
        return {"ok": True, "balance": {"totalUsd": 1234.0}, "positions": None}


def _loop(venue_ok=True, fill_price=0.0):
    scfg = StrategyConfig()
    rcfg = RuntimeConfig(venue="pancake", use_testnet=False,
                         confirm_receipts=False, venue_max_retries=1)
    eng = ExecutionEngine(scfg, deposit_usd=10_000.0)
    orch = Orchestrator(scfg, eng)
    loop = LiveLoop(scfg, rcfg, eng, orch)
    fake = FakeVenue(ok=venue_ok, fill_price=fill_price)
    loop.spot_venue = fake
    loop.perp_venue = fake
    return loop, eng, fake


def test_hook_open_failure_rolls_back():
    loop, eng, fake = _loop(venue_ok=False)
    pos = eng.open_from_signal(_signal(), fill_price=100.0, ts=_ts())
    assert pos in eng.positions
    loop._venue_open(pos)
    # venue failed after retries -> phantom removed, books == chain (nothing)
    assert pos not in eng.positions
    assert fake.opens == loop.rcfg.venue_max_retries + 1


def test_hook_open_success_reconciles_fill():
    loop, eng, fake = _loop(venue_ok=True, fill_price=101.0)
    pos = eng.open_from_signal(_signal(level=100.0), fill_price=100.0, ts=_ts())
    loop._venue_open(pos)
    assert pos in eng.positions
    assert pos.avg_entry == pytest.approx(101.0)        # reconciled to real fill
    assert pos.meta["venue_tx"] == "0xopen"


def test_hook_close_failure_reverts_and_halts():
    loop, eng, fake = _loop(venue_ok=False)
    pos = eng.open_from_signal(_signal(level=100.0), fill_price=100.0, ts=_ts())
    trade = eng._close(pos, 105.0, _ts(), reason="take_profit")
    loop._venue_close(trade)
    # close failed on-chain -> reverted (still open) + new opens halted
    assert pos.state in (PositionState.OPEN, PositionState.SL_IN_PROFIT)
    assert trade not in eng.closed
    assert eng.trading_halted is True
    assert "close failed" in eng.halt_reason


def test_hook_close_success_reconciles_and_stores_tx():
    loop, eng, fake = _loop(venue_ok=True, fill_price=104.0)
    pos = eng.open_from_signal(_signal(level=100.0), fill_price=100.0, ts=_ts())
    trade = eng._close(pos, 105.0, _ts(), reason="take_profit")
    loop._venue_close(trade)
    assert pos.meta["venue_close_tx"] == "0xclose"
    assert pos.meta["venue_close_fill"] == pytest.approx(104.0)
    assert trade.pnl_usd == pytest.approx(pos.realized_pnl_usd)
    assert eng.trading_halted is False


# --------------------------------------------------------------------------
# Blocker 5 — boot reconcile halts on unverified restored positions
# --------------------------------------------------------------------------

def test_boot_reconcile_halts_until_ack():
    loop, eng, fake = _loop(venue_ok=True)
    # simulate a warm restart that restored an open position
    eng.open_from_signal(_signal(), fill_price=100.0, ts=_ts())
    loop.reconcile_on_boot()
    assert loop.reconcile_state == "pending_ack"
    assert eng.trading_halted is True
    # human ack clears it
    out = loop.ack_reconcile()
    assert out["reconcile_state"] == "clean"
    assert eng.trading_halted is False


def test_boot_reconcile_clean_when_flat():
    loop, eng, fake = _loop(venue_ok=True)
    loop.reconcile_on_boot()
    assert loop.reconcile_state == "clean"
    assert eng.trading_halted is False


def test_boot_reconcile_auto_ack():
    scfg = StrategyConfig()
    rcfg = RuntimeConfig(venue="pancake", use_testnet=False, reconcile_auto_ack=True)
    eng = ExecutionEngine(scfg, deposit_usd=10_000.0)
    orch = Orchestrator(scfg, eng)
    loop = LiveLoop(scfg, rcfg, eng, orch)
    loop.spot_venue = loop.perp_venue = FakeVenue()
    eng.open_from_signal(_signal(), fill_price=100.0, ts=_ts())
    loop.reconcile_on_boot()
    assert loop.reconcile_state == "clean"
    assert eng.trading_halted is False
