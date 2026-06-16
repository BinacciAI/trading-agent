import os
from binacci.config import StrategyConfig, RuntimeConfig
from binacci.metalearn import run_optimization, _candidates, _score

def test_grid_and_score():
    assert len(_candidates()) == 8
    assert _score(2.0, 4.0) == 0.5
    assert _score(1.0, 0.0) == 2.0   # floor on drawdown

def test_optimization_proposes_best():
    os.environ["BINACCI_SIMULATE_FEES"] = "true"
    base = StrategyConfig(); base.margin.entry_pct_of_working = 0.02; base.risk.max_positions = 10
    p = run_optimization(base, RuntimeConfig(), ["BNB", "ETH", "CAKE"], source="synthetic", bars=350)
    assert p["best"] is not None and len(p["candidates"]) >= 1
    assert "perps_leverage" in p["best"] and "score" in p["best"]
    assert p["candidates"][0]["score"] >= p["candidates"][-1]["score"]  # sorted best-first
    del os.environ["BINACCI_SIMULATE_FEES"]
