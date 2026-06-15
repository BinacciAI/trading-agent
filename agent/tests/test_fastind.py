"""Equivalence harness for the backtest fast path.

The backtest shares the live trading engine, so every speedup is gated on
producing *identical* results to the canonical pandas implementation:

* each vectorized indicator matches its pandas reference to fp noise,
* the vectorized ``local_extrema`` returns identical pivot indices,
* a full backtest produces bit-identical trades with the fast path on vs off,
* the parallel universe sweep produces a byte-identical report to the serial
  sweep.

If any of these break, the fast path is no longer a safe drop-in and must not
ship enabled.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

import binacci.indicators as I
from binacci.config import StrategyConfig, Timeframe
from binacci.data import SyntheticSource
from binacci.backtest import run_backtest, run_full_backtest
from binacci.levels import local_extrema


def _ohlcv(n: int, seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100 + np.cumsum(rng.normal(0, 1, n))
    high = close + np.abs(rng.normal(0, 0.5, n))
    low = close - np.abs(rng.normal(0, 0.5, n))
    vol = np.abs(rng.normal(1000, 200, n))
    return pd.DataFrame({"open": close, "high": high, "low": low,
                         "close": close, "volume": vol})


def _max_diff(a: pd.Series, b: pd.Series) -> float:
    a = a.to_numpy(); b = b.to_numpy()
    mask = ~(np.isnan(a) & np.isnan(b))
    return float(np.nanmax(np.abs((a - b)[mask]))) if mask.any() else 0.0


@pytest.mark.parametrize("n", [60, 120, 400, 800])
def test_indicators_match_pandas(n):
    df = _ohlcv(n, seed=n)
    c = df["close"]
    try:
        I.FAST_INDICATORS = False
        ref = {
            "sma": I.sma(c, 20), "ema": I.ema(c, 21), "rsi": I.rsi(c, 14),
            "bb_lo": I.bollinger(c, 20)[0], "bb_up": I.bollinger(c, 20)[2],
            "atr": I.atr(df, 14), "vr": I.volume_ratio(df["volume"], 20),
            "cmd": I.cmd(c, 9, 26), "ich_a": I.ichimoku(df)[2],
        }
        I.FAST_INDICATORS = True
        fast = {
            "sma": I.sma(c, 20), "ema": I.ema(c, 21), "rsi": I.rsi(c, 14),
            "bb_lo": I.bollinger(c, 20)[0], "bb_up": I.bollinger(c, 20)[2],
            "atr": I.atr(df, 14), "vr": I.volume_ratio(df["volume"], 20),
            "cmd": I.cmd(c, 9, 26), "ich_a": I.ichimoku(df)[2],
        }
    finally:
        I.FAST_INDICATORS = True
    for k in ref:
        assert _max_diff(ref[k], fast[k]) < 1e-9, f"{k} diverged"


@pytest.mark.parametrize("window", [8, 12, 20])
def test_local_extrema_vectorized_matches_loop(window):
    df = _ohlcv(500, seed=window)
    lows = df["low"].to_numpy(); highs = df["high"].to_numpy(); n = len(df)
    exp_min, exp_max = [], []
    for i in range(window, n - window):
        if lows[i] == lows[i - window:i + window + 1].min():
            exp_min.append(i)
        if highs[i] == highs[i - window:i + window + 1].max():
            exp_max.append(i)
    got_min, got_max = local_extrema(df, window)
    assert got_min == exp_min
    assert got_max == exp_max


def _trades(res):
    return [(t["symbol"], t["tf"], t["strategy"], t["side"],
             round(t["pnl_usd"], 6), t["reason"]) for t in res.trade_log]


@pytest.mark.parametrize("sym", ["BNB", "ETH", "CAKE", "XRP", "LINK"])
def test_backtest_fast_equivalent_to_slow(sym):
    cfg = StrategyConfig(); cfg.apply_risk_mode("balanced")
    try:
        I.FAST_INDICATORS = False
        slow = run_backtest(cfg, SyntheticSource(seed=hash(sym) % 100), sym,
                            Timeframe.M15, bars=500, eval_every=1)
        I.FAST_INDICATORS = True
        fast = run_backtest(cfg, SyntheticSource(seed=hash(sym) % 100), sym,
                            Timeframe.M15, bars=500, eval_every=1)
    finally:
        I.FAST_INDICATORS = True
    assert _trades(slow) == _trades(fast)
    assert slow.total_pnl_usd == pytest.approx(fast.total_pnl_usd, abs=1e-9)


def test_parallel_sweep_equivalent_to_serial():
    cfg = StrategyConfig()
    syms = ["BNB", "ETH", "CAKE", "XRP", "LINK", "SOL"]
    src = SyntheticSource(seed=7)
    serial = run_full_backtest(cfg, src, symbols=syms, timeframes=[Timeframe.M15],
                               bars=400, eval_every=3, workers=1)
    parallel = run_full_backtest(cfg, src, symbols=syms, timeframes=[Timeframe.M15],
                                 bars=400, eval_every=3, workers=2)
    assert json.dumps(serial, sort_keys=True, default=str) == \
           json.dumps(parallel, sort_keys=True, default=str)


@pytest.mark.parametrize("sym,tf", [
    ("BNB", Timeframe.M15), ("ETH", Timeframe.M15), ("CAKE", Timeframe.H4),
    ("SOL", Timeframe.M30), ("ADA", Timeframe.M15), ("DOT", Timeframe.M15),
])
def test_precompute_backtest_identical(sym, tf):
    """BINACCI_FAST_BACKTEST precompute path must yield identical trades to the
    canonical per-bar path. Indicators are causal so the precompute is
    lookahead-free; find_divergences bypasses it (seg-seeded RSI)."""
    import binacci.backtest as bt
    cfg = StrategyConfig(); cfg.apply_risk_mode("balanced")
    try:
        bt.FAST_BACKTEST = False
        off = run_backtest(cfg, SyntheticSource(seed=hash(sym) % 100), sym, tf,
                           bars=700, eval_every=1)
        bt.FAST_BACKTEST = True
        on = run_backtest(cfg, SyntheticSource(seed=hash(sym) % 100), sym, tf,
                          bars=700, eval_every=1)
    finally:
        bt.FAST_BACKTEST = False
    assert _trades(off) == _trades(on)
    assert off.total_pnl_usd == pytest.approx(on.total_pnl_usd, abs=1e-9)
