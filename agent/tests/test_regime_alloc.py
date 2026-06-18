from binacci.config import StrategyConfig, REGIME_WEIGHTS

def test_weights_bounded_and_tilted():
    cfg = StrategyConfig()
    # weights never exceed 1.0 (only ever trim risk)
    for reg, m in REGIME_WEIGHTS.items():
        for s, w in m.items():
            assert 0.0 <= w <= 1.0
    # risk_on favours trend/momentum over fades; risk_off cuts spot longs
    assert cfg.regime_size_mult("risk_on", "trend_follow") == 1.0
    assert cfg.regime_size_mult("risk_on", "vwap_reversion") < 1.0
    assert cfg.regime_size_mult("risk_off", "trend_follow") < cfg.regime_size_mult("chop", "trend_follow")
    # chop favours the perp fades
    assert cfg.regime_size_mult("chop", "vwap_reversion") == 1.0
    # unknown regime / disabled -> neutral 1.0
    assert cfg.regime_size_mult("unknown", "reaction") == 1.0
    cfg.regime_weighting = False
    assert cfg.regime_size_mult("risk_off", "trend_follow") == 1.0

def test_size_mult_scales_notional():
    from datetime import datetime, timezone
    from binacci.execution import ExecutionEngine
    from binacci.models import EntrySignal, ReferencePoint, RefKind, Side, Timeframe
    cfg = StrategyConfig()
    e = ExecutionEngine(cfg, 100000.0)
    ref = ReferencePoint("X", Timeframe.M15, RefKind.LOCAL_MIN, 99.0, datetime.now(timezone.utc))
    def sig(strat, mult):
        return EntrySignal(symbol=f"M{mult}", timeframe=Timeframe.M15, side=Side.LONG, level_price=100.0,
            reference=ref, gates=[], ts=datetime.now(timezone.utc), target_pct=0.5, strategy=strat,
            meta={"strategy": strat, "size_mult": mult})
    full = e.open_from_signal(sig("trend_follow", 1.0), 100.0, datetime.now(timezone.utc))
    half = e.open_from_signal(sig("trend_follow", 0.5), 100.0, datetime.now(timezone.utc))
    assert abs(half.notional_usd - full.notional_usd * 0.5) < 1e-6
