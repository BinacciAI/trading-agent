"""Tests for risk-mode leverage tiers, the time-basis helpers, and the
full-universe multi-timeframe backtest."""

import os

import pytest

from binacci.config import StrategyConfig, Timeframe, RiskMode
from binacci.timebase import (bars_to_minutes, bars_to_timedelta,
                              humanize_duration, timebasis_table)
from binacci.backtest import run_full_backtest
from binacci.data import SyntheticSource


# ---------------- leverage tiers ----------------

def test_leverage_tiers_by_mode():
    assert StrategyConfig().apply_risk_mode("conservative").perps_leverage == 10.0
    assert StrategyConfig().apply_risk_mode("balanced").perps_leverage == 25.0
    assert StrategyConfig().apply_risk_mode("aggressive").perps_leverage == 50.0


def test_bare_constructor_keeps_raw_leverage():
    # production goes through load(); the bare ctor must stay at 2.0 so the
    # rest of the unit suite keeps deterministic raw defaults.
    assert StrategyConfig().perps_leverage == 2.0


def test_load_balanced_is_25x_and_target_2x(monkeypatch):
    monkeypatch.delenv("BINACCI_PERPS_LEVERAGE", raising=False)
    monkeypatch.setenv("BINACCI_RISK_MODE", "balanced")
    cfg = StrategyConfig.load()
    assert cfg.perps_leverage == 25.0
    assert cfg.perps_target_mult == 2.0
    # load() exports the resolved leverage so env-reading consumers agree
    assert os.environ["BINACCI_PERPS_LEVERAGE"] == "25.0"


def test_explicit_env_overrides_preset(monkeypatch):
    monkeypatch.setenv("BINACCI_RISK_MODE", "aggressive")
    monkeypatch.setenv("BINACCI_PERPS_LEVERAGE", "12")
    cfg = StrategyConfig.load()
    assert cfg.perps_leverage == 12.0  # explicit env beats the 50x preset


def test_risk_summary_exposes_leverage():
    cfg = StrategyConfig().apply_risk_mode("aggressive")
    rs = cfg.risk_summary()
    assert rs["perps_leverage"] == 50.0
    assert rs["perps_target_mult"] == 2.0


# ---------------- time basis ----------------

def test_bars_to_minutes_exact():
    assert bars_to_minutes(1500, Timeframe.M15) == 1500 * 15
    assert bars_to_timedelta(100, Timeframe.H4).total_seconds() == 100 * 240 * 60


def test_humanize_scales_units():
    assert humanize_duration(30) == "30 min"
    assert "hours" in humanize_duration(180)
    assert "days" in humanize_duration(1500 * 15)      # 15m * 1500 ~ 15.6 days
    assert "years" in humanize_duration(1500 * 1440)   # 1d * 1500 ~ 4.1 years


def test_timebasis_table_sorted_and_complete():
    rows = timebasis_table(1500, [Timeframe.D1, Timeframe.M3, Timeframe.M15])
    assert [r["timeframe"] for r in rows] == ["3m", "15m", "1d"]  # shortest first
    m3 = rows[0]
    assert m3["bars"] == 1500 and m3["total_minutes"] == 1500 * 3


# ---------------- full backtest ----------------

def test_full_backtest_structure_and_breakdowns():
    cfg = StrategyConfig()
    res = run_full_backtest(
        cfg, SyntheticSource(seed=7),
        symbols=["BNB", "ETH", "CAKE", "LINK"],
        timeframes=[Timeframe.M15, Timeframe.H4],
        bars=700, deposit_usd=1000.0, risk_mode="balanced",
    )
    # config envelope reflects the applied mode
    assert res["config"]["perps_leverage"] == 25.0
    assert res["config"]["perps_target_mult"] == 2.0
    assert res["config"]["markets_in_universe"] == 4
    assert res["config"]["timeframes"] == ["15m", "4h"]

    # portfolio roll-up is internally consistent
    pf = res["portfolio"]
    assert pf["runs_attempted"] == 4 * 2
    assert pf["runs_completed"] + pf["runs_skipped"] == pf["runs_attempted"]

    # breakdown sections exist and carry the time basis
    assert set(res["by_timeframe"].keys()) == {"15m", "4h"}
    assert res["by_timeframe"]["15m"]["timebasis"]["bars"] == 700
    assert len(res["time_basis"]) == 2
    # spot/perp split only contains known books
    assert set(res["by_market"].keys()) <= {"spot", "perp"}


def test_full_backtest_pnl_consistency():
    """Per-strategy pnl must sum to the portfolio pnl (accounting closes)."""
    cfg = StrategyConfig()
    res = run_full_backtest(
        cfg, SyntheticSource(seed=3),
        symbols=["BNB", "ETH"], timeframes=[Timeframe.M15],
        bars=700, risk_mode="balanced",
    )
    strat_sum = round(sum(v["total_pnl_usd"] for v in res["by_strategy"].values()), 2)
    assert strat_sum == pytest.approx(res["portfolio"]["total_pnl_usd"], abs=0.1)
