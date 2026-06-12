"""Indicators, simulations, backtest, and skill spec — smoke + invariants."""

import pandas as pd
import pytest

from binacci.config import StrategyConfig, Timeframe
from binacci.data import SyntheticSource
from binacci.divergence import find_divergences
from binacci.indicators import bollinger, cmd, ichimoku, rsi, to_dataframe
from binacci.levels import fib_pivots, fib_retracements, local_extrema, log_support_resistance
from binacci.macro import MacroSnapshot, evaluate_macro
from binacci.models import Side
from binacci.simulations import (
    ReferenceBook, Sim01ColdStart, Sim03CleanReference, SimAEntryZone, SimBEntryLevel,
)


@pytest.fixture(scope="module")
def df():
    candles = SyntheticSource(seed=11).history("BNB", Timeframe.M15, 600)
    return to_dataframe(candles)


def test_indicators_shapes(df):
    r = rsi(df["close"])
    assert r.between(0, 100).all()
    lo, mid, up = bollinger(df["close"])
    valid = mid.dropna().index
    assert (lo[valid] <= up[valid]).all()
    c = cmd(df["close"])
    assert len(c) == len(df)
    t, k, sa, sb = ichimoku(df)
    assert len(t) == len(df)


def test_levels(df):
    mins, maxs = local_extrema(df, 12)
    assert mins and maxs
    fr = fib_retracements(100.0, 110.0)
    assert any(abs(l.price - 103.82) < 0.01 for l in fr)  # 0.618 retrace
    assert fib_pivots(df)
    assert log_support_resistance(df)


def test_divergence_detector(df):
    divs = find_divergences(df, lookback=200)
    for d in divs:
        assert d.kind in ("regular_bull", "regular_bear", "hidden_bull", "hidden_bear")
        assert d.i2 > d.i1


def test_reference_book(df):
    cfg = StrategyConfig()
    book = ReferenceBook()
    ref = Sim01ColdStart(cfg.sims).run("BNB", Timeframe.M15, df, book)
    assert ref is not None
    assert book.get("BNB", Timeframe.M15) is ref
    clean = Sim03CleanReference(cfg.sims, cfg.filters).step("BNB", Timeframe.M15, df, book)
    assert clean is not None and clean.clean
    assert "rsi" in clean.meta and "volume_ratio" in clean.meta


def test_sim_a_b(df):
    cfg = StrategyConfig()
    zone = SimAEntryZone(cfg.sims, cfg.filters).assess(df, Side.LONG)
    assert isinstance(zone.in_zone, bool)
    assert set(zone.filter_detail) >= {"cmd", "rsi", "volume_ratio"}
    level = SimBEntryLevel(cfg.sims).pick(df, Side.LONG)
    if level is not None:
        assert level.price <= float(df["close"].iloc[-1]) * 1.01


def test_macro_gate():
    cfg = StrategyConfig().macro
    good = MacroSnapshot(3e12, 55.0, 4.0, total_cap_change_pct=0.5,
                         btc_dominance_change_pct=0.1, usdt_dominance_change_pct=-0.1)
    assert evaluate_macro(good, cfg, Side.LONG).ok
    risk_off = MacroSnapshot(3e12, 55.0, 5.0, total_cap_change_pct=-3.0,
                             btc_dominance_change_pct=1.5, usdt_dominance_change_pct=1.2)
    assert not evaluate_macro(risk_off, cfg, Side.LONG).ok
    # fail closed without data
    assert not evaluate_macro(None, cfg, Side.LONG).ok


def test_backtest_runs():
    from binacci.backtest import run_backtest

    cfg = StrategyConfig()
    res = run_backtest(cfg, SyntheticSource(seed=7), "BNB", Timeframe.M15,
                       bars=1500, deposit_usd=1000.0)
    s = res.summary()
    assert s["bars"] == 1300
    assert res.max_drawdown_pct < 30.0  # risk model holds in backtest
    # equity curve accounting is consistent
    assert res.total_pnl_usd == pytest.approx(
        sum(t["pnl_usd"] for t in res.trade_log), abs=0.1)


def test_skill_spec():
    from binacci.skill import generate_strategy_spec, skill_manifest

    cfg = StrategyConfig()
    spec = generate_strategy_spec(cfg, symbol="BNB", tf=Timeframe.M15,
                                  backtest_bars=800)
    assert spec["skill"] == "binacci-reaction-strategy"
    assert len(spec["strategy"]["entry_chain"]) == 5
    ex = spec["strategy"]["execution"]
    assert ex["margin_model"]["reserve_pct"] == 0.30
    assert ex["risk_limits"]["max_positions"] == 5
    assert "backtest" in spec and "provenance" in spec
    m = skill_manifest()
    assert m["name"] == "binacci-reaction-strategy"
