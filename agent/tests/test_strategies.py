"""Multi-strategy portfolio: registry, isolation, concurrent positions,
universe, and per-strategy Track-2 specs."""

from datetime import datetime, timezone

import pytest

from binacci.config import StrategyConfig, Timeframe
from binacci.data import SyntheticSource
from binacci.execution import ExecutionEngine
from binacci.indicators import to_dataframe
from binacci.models import EntrySignal, ReferencePoint, RefKind, Side
from binacci.orchestrator import Orchestrator
from binacci.strategies import (
    ALL_STRATEGY_NAMES, build_strategies, get_strategy,
    MomentumBreakoutStrategy, MeanReversionStrategy, TrendFollowStrategy,
    VolatilitySqueezeStrategy, ReactionStrategy,
)


def _ts():
    return datetime.now(timezone.utc)


def test_registry_builds_all_strategies():
    cfg = StrategyConfig()
    strats = build_strategies(cfg)
    assert [s.name for s in strats] == ALL_STRATEGY_NAMES
    assert len(strats) == 7
    # reaction is always first (the core)
    assert isinstance(strats[0], ReactionStrategy)


def test_toggles_disable_strategies():
    cfg = StrategyConfig()
    cfg.strategies.mean_reversion = False
    cfg.strategies.volatility_squeeze = False
    names = [s.name for s in build_strategies(cfg)]
    assert "mean_reversion" not in names
    assert "volatility_squeeze" not in names
    assert "reaction" in names and "momentum_breakout" in names


def test_each_strategy_returns_proposal_or_none():
    cfg = StrategyConfig()
    df = to_dataframe(SyntheticSource(seed=3).history("BNB", Timeframe.M15, 400))
    for name in ALL_STRATEGY_NAMES:
        strat = get_strategy(cfg, name)
        prop = strat.propose("BNB", Timeframe.M15, df, Side.LONG)
        if prop is not None:
            assert prop.strategy == name
            assert prop.level_price > 0
            # entries are always limits at or just below price (long)
            price = float(df["close"].iloc[-1])
            assert prop.level_price <= price * 1.01


def test_concurrent_positions_per_strategy():
    """Two strategies may each hold a position on the SAME (symbol, tf)."""
    eng = ExecutionEngine(StrategyConfig(), deposit_usd=10_000.0)
    ref = ReferencePoint("BNB", Timeframe.M15, RefKind.LOCAL_MIN, 99.0, _ts())

    def sig(strategy):
        return EntrySignal(symbol="BNB", timeframe=Timeframe.M15, side=Side.LONG,
                           level_price=100.0, reference=ref, gates=[], ts=_ts(),
                           target_pct=0.5, strategy=strategy)

    p1 = eng.open_from_signal(sig("reaction"), 100.0, _ts())
    p2 = eng.open_from_signal(sig("momentum_breakout"), 100.0, _ts())
    assert p1 is not None and p2 is not None
    # same strategy + same market = duplicate, refused
    assert eng.open_from_signal(sig("reaction"), 100.0, _ts()) is None
    assert p1.meta["strategy"] == "reaction"
    assert p2.meta["strategy"] == "momentum_breakout"


def test_portfolio_widens_opportunity():
    """The full portfolio must take strictly more trades than reaction-only
    on the same data — the whole point of the multi-strategy engine."""
    from binacci.backtest import run_backtest

    src = SyntheticSource(seed=7)
    only = StrategyConfig()
    for n in ("momentum_breakout", "mean_reversion", "trend_follow", "volatility_squeeze"):
        setattr(only.strategies, n, False)
    full = StrategyConfig()

    r_only = run_backtest(only, src, "BNB", Timeframe.M15, bars=700)
    r_full = run_backtest(full, src, "BNB", Timeframe.M15, bars=700)
    assert r_full.trades > r_only.trades
    # risk model still holds with many strategies active
    assert r_full.max_drawdown_pct < 30.0


def test_universe_is_bsc_weighted():
    cfg = StrategyConfig()
    assert len(cfg.symbols) >= 50
    assert "BNB" in cfg.symbols and "CAKE" in cfg.symbols
    # BTC swaps as BTCB on BSC
    assert cfg.chain_symbol("BTC") == "BTCB"
    assert cfg.chain_symbol("CAKE") == "CAKE"


def test_macro_optional_per_strategy():
    cfg = StrategyConfig()
    assert MeanReversionStrategy(cfg).requires_macro is False  # counter-trend fade
    assert MomentumBreakoutStrategy(cfg).requires_macro is True
    assert TrendFollowStrategy(cfg).requires_macro is True
    assert VolatilitySqueezeStrategy(cfg).requires_macro is True
    assert ReactionStrategy(cfg).requires_reference is True


def test_orchestrator_runs_portfolio():
    cfg = StrategyConfig()
    cfg.macro.enabled = False
    eng = ExecutionEngine(cfg, deposit_usd=1000.0)
    orch = Orchestrator(cfg, eng)
    assert len(orch.strategies) == 7
    df = to_dataframe(SyntheticSource(seed=5).history("CAKE", Timeframe.M15, 300))
    orch.cold_start("CAKE", Timeframe.M15, df)
    trace = orch.evaluate("CAKE", Timeframe.M15, df, ts=_ts())
    # traces recorded for multiple strategies in one evaluation pass
    strategies_seen = {t.strategy for t in orch.traces}
    assert len(strategies_seen) >= 2


def test_per_strategy_specs():
    from binacci.skill import (
        generate_strategy_spec, generate_portfolio_spec, all_skill_manifests,
        strategy_catalog,
    )

    cfg = StrategyConfig()
    for name in ALL_STRATEGY_NAMES:
        spec = generate_strategy_spec(cfg, symbol="BNB", tf=Timeframe.M15,
                                      backtest_bars=600, strategy=name)
        assert spec["skill"] == f"binacci-{name.replace('_','-')}-strategy"
        assert spec["strategy_name"] == name
        assert "entry_chain" in spec["strategy"]
        assert "backtest" in spec and "market_state" in spec

    cat = strategy_catalog()
    assert len(cat) == 7
    mans = all_skill_manifests()
    assert len(mans) == 7
    port = generate_portfolio_spec(cfg, symbol="BNB", tf=Timeframe.M15, backtest_bars=600)
    assert len(port["per_strategy"]) == 7
    assert "combined_backtest" in port


def test_minute_builder_real_volume():
    from datetime import timedelta
    from binacci.live import MinuteBuilder

    mb = MinuteBuilder()
    base = datetime(2026, 6, 14, 12, 0, 0, tzinfo=timezone.utc)
    v = 1_000_000.0
    out = []
    for i in range(120):
        v += 50.0  # +100 traded volume per minute (2 ticks/min)
        d = mb.add(base + timedelta(seconds=30 * i), 100.0, vol24h=v)
        if d:
            out.append(d)
    assert out
    # candle volume reflects real traded volume, not the tick count (which
    # would be ~2). 24h-vol delta per minute ≈ 100.
    assert out[1].volume == pytest.approx(100.0, abs=1.0)


def test_runtime_config_complete():
    """Regression guard: RuntimeConfig must keep every field the API/live loop
    reference (a truncated config once dropped use_testnet/wallet_address and
    crashed the /health endpoint in production)."""
    from binacci.config import RuntimeConfig

    rc = RuntimeConfig()
    required = [
        "cmc_api_key", "cmc_base_url", "venue", "deposit_usd", "poll_seconds",
        "macro_refresh_seconds", "fear_greed_refresh_seconds", "poll_only_verified",
        "warmup_backfill", "warmup_backfill_bars", "verify_liquidity",
        "max_price_impact_pct", "twak_endpoint", "bsc_rpc", "bsc_testnet_rpc",
        "wallet_address", "use_testnet", "api_host", "api_port",
    ]
    for f in required:
        assert hasattr(rc, f), f"RuntimeConfig missing {f}"


def test_universe_backtest_runs():
    from binacci.backtest import run_universe_backtest
    from binacci.config import StrategyConfig, Timeframe
    from binacci.data import SyntheticSource

    res = run_universe_backtest(StrategyConfig(), SyntheticSource(),
                                ["BNB", "CAKE", "ETH"], Timeframe.M15,
                                bars=400, eval_every=2)
    assert res["markets_tested"] == 3
    assert res["winners"] + res["losers"] == 3
    assert "per_symbol" in res and len(res["per_symbol"]) == 3
