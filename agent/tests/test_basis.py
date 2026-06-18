from datetime import datetime, timezone
from binacci.config import StrategyConfig, Timeframe
from binacci.execution import ExecutionEngine
from binacci.models import EntrySignal, ReferencePoint, RefKind, Side, PositionState
from binacci.basis import expected_carry_pct, basis_skill_manifest
from binacci.strategies import ALL_STRATEGY_NAMES

def _ts(): return datetime.now(timezone.utc)

def test_registered():
    assert "basis_carry" in ALL_STRATEGY_NAMES and len(ALL_STRATEGY_NAMES) == 9
    assert StrategyConfig().market_for("basis_carry") == "perp"
    assert StrategyConfig().market_for("basis_hedge") == "spot"   # hedge leg routes to spot
    assert basis_skill_manifest()["delta_neutral"] is True

def test_carry_hedge_delta_neutral_and_cascade():
    cfg = StrategyConfig(); e = ExecutionEngine(cfg, 100000.0); ts = _ts()
    ref = ReferencePoint("BNB", Timeframe.M15, RefKind.LOCAL_MAX, 101.0, ts)
    sig = EntrySignal(symbol="BNB", timeframe=Timeframe.M15, side=Side.SHORT, level_price=100.0,
                      reference=ref, gates=[], ts=ts, target_pct=1.0, strategy="basis_carry",
                      meta={"strategy": "basis_carry", "carry": True})
    perp = e.open_from_signal(sig, 100.0, ts)
    hedge = e.open_carry_hedge(perp, 100.0, ts)
    assert hedge is not None and hedge.side is Side.LONG
    assert e.cfg.market_for(hedge.meta["strategy"]) == "spot"
    assert abs(hedge.notional_usd - perp.notional_usd) < 1e-6   # equal notional = delta-neutral
    # closing the perp leg cascades to close the spot hedge
    e._close(perp, 100.0, ts, "test")
    assert hedge.state is PositionState.CLOSED
