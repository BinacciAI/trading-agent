"""Execution engine invariants — the numbers from the strategy doc."""

from datetime import datetime, timezone

import pytest

from binacci.config import StrategyConfig, Timeframe
from binacci.execution import ExecutionEngine
from binacci.models import EntrySignal, PositionState, ReferencePoint, RefKind, Side


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


def test_margin_model_numbers():
    cfg = StrategyConfig()
    assert cfg.margin.working_pct == pytest.approx(0.70)
    # 0.5% of working margin = 0.35% of deposit
    assert cfg.margin.entry_pct_of_deposit == pytest.approx(0.0035)
    # x4 then x2 -> ~2.8% (doc: "~3%") cap per fully averaged position
    assert cfg.margin.position_cap_pct() == pytest.approx(0.028)


def test_entry_sizing(engine):
    assert engine.entry_notional_usd() == pytest.approx(35.0)  # 0.35% of 10k


def test_averaging_ladder(engine):
    pos = engine.open_from_signal(_signal(), fill_price=100.0, ts=_ts())
    # 1st averaging: x4 -> target 140 USD total, add 105
    add1 = engine.averaging_notional_usd(pos)
    assert add1 == pytest.approx(105.0)
    assert engine.try_average(pos, 99.0, 99.0, _ts())
    assert pos.notional_usd == pytest.approx(140.0)
    # 2nd averaging: x2 -> target 280 USD total, add 140
    add2 = engine.averaging_notional_usd(pos)
    assert add2 == pytest.approx(140.0)
    assert engine.try_average(pos, 98.0, 98.0, _ts())
    assert pos.notional_usd == pytest.approx(280.0)  # 2.8% of deposit
    # no third averaging
    assert engine.averaging_notional_usd(pos) is None


def test_averaging_requires_drawdown(engine):
    pos = engine.open_from_signal(_signal(), fill_price=100.0, ts=_ts())
    # price above entry -> averaging refused
    assert not engine.try_average(pos, 101.0, 101.0, _ts())


def test_max_positions_and_smart_slot_return(engine):
    cfg = engine.cfg
    cfg.book_share = 1.0  # isolate slot mechanics from the per-book cap
    for i in range(cfg.risk.max_positions):
        sig = _signal(symbol=f"C{i}")
        assert engine.open_from_signal(sig, 100.0, _ts()) is not None
    # 6th refused
    assert engine.open_from_signal(_signal(symbol="C5"), 100.0, _ts()) is None
    assert engine.slots_free() == 0

    # move 3 positions' SL into profit -> slots released (smart slot return)
    for p in engine.positions[:3]:
        engine.on_price(p, 100.0 * (1 + cfg.trailing.trigger_pct / 100), _ts())
        assert p.state is PositionState.SL_IN_PROFIT
    assert engine.slots_free() == 3


def test_trailing_ladder():
    cfg = StrategyConfig()
    t = cfg.trailing
    assert t.stop_for(0.39) is None          # below trigger
    assert t.stop_for(0.40) == pytest.approx(0.20)
    assert t.stop_for(0.50) == pytest.approx(0.30)
    assert t.stop_for(0.90) == pytest.approx(0.70)  # doc ladder


def test_trailing_stop_close(engine):
    pos = engine.open_from_signal(_signal(target=5.0), 100.0, _ts())
    engine.on_price(pos, 100.6, _ts())   # peak +0.6% -> SL +0.4%
    assert pos.stop_pct == pytest.approx(0.40)
    trade = engine.on_price(pos, 100.40, _ts())  # falls to SL
    assert trade is not None and trade.reason == "trailing_stop"
    assert trade.pnl_usd > 0  # closed green


def test_take_profit(engine):
    pos = engine.open_from_signal(_signal(target=0.5), 100.0, _ts())
    trade = engine.on_price(pos, 100.51, _ts())
    assert trade is not None and trade.reason == "take_profit"


def test_disabled_book_blocks_new_opens(engine):
    cfg = engine.cfg
    # reaction is a spot strategy. Disable the spot book -> no new spot opens,
    # but the perps book is unaffected.
    cfg.spot_enabled = False
    assert not engine.can_open("BNB", Timeframe.M15, "reaction")
    assert engine.open_from_signal(_signal(), 100.0, _ts()) is None
    assert engine.can_open("BNB", Timeframe.M15, "mean_reversion")  # perp book
    cfg.spot_enabled = True
    assert engine.open_from_signal(_signal(), 100.0, _ts()) is not None


def test_flatten_closes_open_positions(engine):
    cfg = engine.cfg
    cfg.book_share = 1.0
    for i in range(3):
        engine.open_from_signal(_signal(symbol=f"F{i}"), 100.0, _ts())
    assert len(engine.open_positions()) == 3
    prices = {f"F{i}": 100.5 for i in range(3)}
    closed = engine.flatten(prices, _ts(), reason="operator_close")
    assert len(closed) == 3
    assert all(t.reason == "operator_close" for t in closed)
    assert engine.open_positions() == []


def test_flatten_scoped_to_book(engine):
    cfg = engine.cfg
    cfg.book_share = 1.0
    spot = engine.open_from_signal(_signal(symbol="SP"), 100.0, _ts())  # reaction=spot
    perp_sig = _signal(symbol="PP")
    perp_sig.strategy = "mean_reversion"  # perp book
    perp = engine.open_from_signal(perp_sig, 100.0, _ts())
    assert spot is not None and perp is not None
    closed = engine.flatten({"SP": 100.0, "PP": 100.0}, _ts(), market="spot")
    assert len(closed) == 1 and closed[0].position.symbol == "SP"
    # the perp position is untouched
    remaining = engine.open_positions()
    assert len(remaining) == 1 and remaining[0].symbol == "PP"


def test_kill_switch(engine):
    # open 5 positions, crash all of them far enough that aggregate
    # floating loss >= 30% of deposit
    for i in range(5):
        engine.open_from_signal(_signal(symbol=f"K{i}"), 100.0, _ts())
        p = engine.positions[-1]
        engine.try_average(p, 99.0, 99.0, _ts())
        engine.try_average(p, 98.0, 98.0, _ts())
    # each position ~280 USD; need 3000 USD aggregate loss on 10k deposit.
    # price -> 0.01 of entry: ~99% loss each = ~1386 total -> still < 3000?
    # 5 * 280 = 1400 max loss. Lower deposit to make limit reachable:
    eng2 = ExecutionEngine(StrategyConfig(), deposit_usd=1000.0)
    for i in range(5):
        eng2.open_from_signal(_signal(symbol=f"K{i}"), 100.0, _ts())
        p = eng2.positions[-1]
        eng2.try_average(p, 99.0, 99.0, _ts())
        eng2.try_average(p, 98.0, 98.0, _ts())
    # aggregate notional ~140 USD... kill limit = 300 USD -> unreachable by
    # price alone; that's the doc's double-safety: position caps make the
    # stop-cock nearly impossible to hit with 5 slots. Verify arithmetic:
    prices = {f"K{i}": 1.0 for i in range(5)}  # ~ -99%
    dd = eng2.aggregate_drawdown_usd(prices)
    assert dd < eng2.account.deposit_usd * eng2.cfg.risk.max_aggregate_drawdown_pct
    assert eng2.check_kill_switch(prices, _ts()) == []

    # with a stressed config (more slots) the switch must fire and close all
    cfg = StrategyConfig()
    cfg.risk.max_positions = 60
    cfg.book_share = 1.0  # let a single book hold all 60 so we test the switch,
    #                       not the per-book cap (covered elsewhere)
    eng3 = ExecutionEngine(cfg, deposit_usd=1000.0)
    for i in range(60):
        eng3.open_from_signal(_signal(symbol=f"S{i}"), 100.0, _ts())
        p = eng3.positions[-1]
        eng3.try_average(p, 99.0, 99.0, _ts())
        eng3.try_average(p, 98.0, 98.0, _ts())
    prices = {f"S{i}": 70.0 for i in range(60)}  # ~ -29% each
    closed = eng3.check_kill_switch(prices, _ts())
    assert eng3.kill_switch_fired
    assert len(closed) == 60
    assert all(t.reason == "kill_switch" for t in closed)
    # after kill switch, no new entries
    assert not eng3.can_open("NEW", Timeframe.M15)
