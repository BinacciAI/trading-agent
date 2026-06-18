import os
from datetime import datetime, timezone, timedelta
from binacci.fees import FeeModel
from binacci.config import StrategyConfig, Timeframe
from binacci.execution import ExecutionEngine
from binacci.models import EntrySignal, ReferencePoint, RefKind, Side

def test_breakeven_and_roundtrip():
    m = FeeModel()
    assert abs(m.breakeven_move_pct("spot") - 0.50) < 1e-9   # 2 x 0.25%
    assert abs(m.breakeven_move_pct("perp") - 0.16) < 1e-9   # 2 x 0.08%
    # spot round trip on $100 notional: 0.5% fee + 2 gas
    assert abs(m.spot_roundtrip_usd(100.0) - (100*0.005 + m.gas_usd*2)) < 1e-9

def test_engine_books_net_of_fees():
    cfg = StrategyConfig()
    e = ExecutionEngine(cfg, 100000.0)
    e._simulate_fees = True
    ts = datetime.now(timezone.utc)
    ref = ReferencePoint("X", Timeframe.M15, RefKind.LOCAL_MIN, 99.0, ts)
    sig = EntrySignal(symbol="X", timeframe=Timeframe.M15, side=Side.LONG, level_price=100.0,
                      reference=ref, gates=[], ts=ts, target_pct=2.0, strategy="trend_follow",
                      meta={"strategy": "trend_follow"})
    pos = e.open_from_signal(sig, 100.0, ts)
    t = e.on_price(pos, 102.0, ts + timedelta(minutes=5))  # +2%
    assert t is not None
    assert t.fees_usd > 0 and t.gross_pnl_usd > t.pnl_usd
    assert abs(t.pnl_usd - (t.gross_pnl_usd - t.fees_usd)) < 1e-6

def test_min_edge_gate_blocks_fee_losers():
    # a tiny-notional spot setup with a sub-breakeven target must be refused
    from binacci.orchestrator import Orchestrator
    cfg = StrategyConfig(); cfg.min_edge_gate = True; cfg.macro.enabled = False
    eng = ExecutionEngine(cfg, 1000.0)  # entry ~ $3.5 notional -> gas dominates
    orch = Orchestrator(cfg, eng)
    from binacci.data import SyntheticSource
    from binacci.indicators import to_dataframe
    df = to_dataframe(SyntheticSource(seed=5).history("BNB", Timeframe.M3, 300))
    orch.cold_start("BNB", Timeframe.M3, df)
    orch.evaluate("BNB", Timeframe.M3, df, ts=datetime.now(timezone.utc))
    # with the gate on at tiny size, no spot M3 setup should park a level
    parked = [p for p in orch.pending if cfg.market_for(p.signal.strategy) == "spot"]
    assert parked == []
