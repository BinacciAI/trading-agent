from binacci.funding import basis_implied_funding, classify_funding
from binacci.config import StrategyConfig, Timeframe
from binacci.data import SyntheticSource
from binacci.indicators import to_dataframe
from binacci.strategies import build_strategies, get_strategy, ALL_STRATEGY_NAMES
from binacci.models import Side

def test_basis_and_classify():
    assert basis_implied_funding(101.0, 100.0) == 1.0
    assert classify_funding(0.2, 0.05)["fade_side"] == "short"   # premium -> fade short
    assert classify_funding(-0.2, 0.05)["fade_side"] == "long"
    assert classify_funding(0.01, 0.05)["state"] == "neutral"

def test_funding_strategy_registered():
    assert "funding_carry" in ALL_STRATEGY_NAMES and len(ALL_STRATEGY_NAMES) == 8
    cfg = StrategyConfig()
    assert cfg.market_for("funding_carry") == "perp"
    assert "funding_carry" in {s.name for s in build_strategies(cfg)}

def test_funding_strategy_fires_only_on_extreme():
    cfg = StrategyConfig()
    s = get_strategy(cfg, "funding_carry")
    df = to_dataframe(SyntheticSource(seed=3).history("BNB", Timeframe.M15, 100))
    # no funding injected -> idle
    assert s.propose("BNB", Timeframe.M15, df, Side.SHORT) is None
    # crowded longs (premium) -> fade SHORT fires, LONG does not
    s.funding_provider = lambda: {"BNB": 0.3}
    assert s.propose("BNB", Timeframe.M15, df, Side.SHORT) is not None
    assert s.propose("BNB", Timeframe.M15, df, Side.LONG) is None
