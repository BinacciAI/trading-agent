"""Event-driven backtester — runs the SAME orchestrator + execution engine
used live, bar by bar. No separate "backtest logic" to drift from prod.

Also powers Track 2: every generated strategy spec ships with a backtest
report computed by this engine, making the spec verifiably backtestable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd

from .config import StrategyConfig, Timeframe
from .data import CandleSource
from .execution import ExecutionEngine
from .indicators import to_dataframe
from .macro import MacroSnapshot
from .models import Candle
from .orchestrator import Orchestrator


@dataclass
class BacktestResult:
    symbol: str
    timeframe: Timeframe
    bars: int
    start: Optional[datetime]
    end: Optional[datetime]
    deposit_usd: float
    trades: int = 0
    wins: int = 0
    losses: int = 0
    total_pnl_usd: float = 0.0
    max_drawdown_pct: float = 0.0
    win_rate_pct: float = 0.0
    profit_factor: float = 0.0
    sharpe: float = 0.0
    return_pct: float = 0.0
    kill_switch_fired: bool = False
    close_reasons: dict = field(default_factory=dict)
    equity_curve: list[float] = field(default_factory=list)
    trade_log: list[dict] = field(default_factory=list)

    def summary(self) -> dict:
        return {
            "symbol": self.symbol, "timeframe": self.timeframe.value, "bars": self.bars,
            "trades": self.trades, "win_rate_pct": round(self.win_rate_pct, 1),
            "total_pnl_usd": round(self.total_pnl_usd, 2),
            "return_pct": round(self.return_pct, 2),
            "max_drawdown_pct": round(self.max_drawdown_pct, 2),
            "profit_factor": round(self.profit_factor, 2),
            "sharpe": round(self.sharpe, 2),
            "kill_switch_fired": self.kill_switch_fired,
            "close_reasons": self.close_reasons,
        }


def run_backtest(
    cfg: StrategyConfig,
    source: CandleSource,
    symbol: str,
    tf: Timeframe,
    bars: int = 2000,
    deposit_usd: float = 1000.0,
    warmup: int = 200,
    macro_series: Optional[list[MacroSnapshot]] = None,
    eval_every: int = 1,
) -> BacktestResult:
    candles = source.history(symbol, tf, bars)
    if len(candles) <= warmup + 10:
        raise ValueError(f"not enough candles: {len(candles)} (need > {warmup + 10})")

    engine = ExecutionEngine(cfg, deposit_usd=deposit_usd)

    macro_idx = {"i": 0}

    def macro_provider() -> Optional[MacroSnapshot]:
        if macro_series:
            return macro_series[min(macro_idx["i"], len(macro_series) - 1)]
        return None

    # Backtests without macro data disable the gate rather than fail closed.
    local_cfg = cfg.model_copy(deep=True)
    if macro_series is None:
        local_cfg.macro.enabled = False

    orch = Orchestrator(local_cfg, engine, macro_provider=macro_provider)

    # Sim01 cold start on the warmup window
    warm_df = to_dataframe(candles[:warmup])
    orch.cold_start(symbol, tf, warm_df)

    equity: list[float] = []
    window: list[Candle] = list(candles[:warmup])
    max_window = max(400, warmup)

    for i in range(warmup, len(candles)):
        c = candles[i]
        window.append(c)
        if len(window) > max_window:
            window.pop(0)
        df = to_dataframe(window)
        macro_idx["i"] = i

        # background sims refresh references each bar
        orch.update_references(symbol, tf, df)

        # entry evaluation (gates 1-4 + park level)
        if i % eval_every == 0:
            orch.evaluate(symbol, tf, df, ts=c.ts)

        # candle stream: fills, averaging, trailing, TP, kill switch
        prices = {symbol: c.close}
        orch.on_candle(symbol, tf, c, prices)

        snap = engine.snapshot(prices)
        equity.append(snap["equity_usd"])

    # close any remaining open positions at the last price (mark-to-market)
    last = candles[-1]
    for p in list(engine.open_positions()):
        engine._close(p, last.close, last.ts, reason="end_of_data")

    return _build_result(symbol, tf, candles, warmup, deposit_usd, engine, equity)


def _build_result(symbol, tf, candles, warmup, deposit_usd, engine, equity) -> BacktestResult:
    res = BacktestResult(
        symbol=symbol, timeframe=tf, bars=len(candles) - warmup,
        start=candles[warmup].ts, end=candles[-1].ts, deposit_usd=deposit_usd,
        equity_curve=equity,
    )
    pnls = [t.pnl_usd for t in engine.closed]
    res.trades = len(pnls)
    res.wins = sum(1 for x in pnls if x > 0)
    res.losses = sum(1 for x in pnls if x <= 0)
    res.total_pnl_usd = float(sum(pnls))
    res.return_pct = res.total_pnl_usd / deposit_usd * 100.0
    res.win_rate_pct = (res.wins / res.trades * 100.0) if res.trades else 0.0
    gross_win = sum(x for x in pnls if x > 0)
    gross_loss = -sum(x for x in pnls if x < 0)
    res.profit_factor = (gross_win / gross_loss) if gross_loss > 0 else (float("inf") if gross_win else 0.0)
    res.kill_switch_fired = engine.kill_switch_fired

    if equity:
        eq = np.array(equity, dtype=float)
        peak = np.maximum.accumulate(eq)
        dd = (peak - eq) / np.where(peak == 0, 1, peak)
        res.max_drawdown_pct = float(dd.max() * 100.0)
        rets = np.diff(eq) / eq[:-1]
        if rets.std() > 0:
            bars_per_year = (365 * 24 * 60) / tf.minutes
            res.sharpe = float(rets.mean() / rets.std() * np.sqrt(bars_per_year))

    for t in engine.closed:
        res.close_reasons[t.reason] = res.close_reasons.get(t.reason, 0) + 1
        res.trade_log.append({
            "symbol": t.position.symbol,
            "tf": t.position.timeframe.value,
            "side": t.position.side.value,
            "avg_entry": round(t.position.avg_entry, 6),
            "averaging_done": t.position.averaging_done,
            "opened": t.position.opened_ts.isoformat() if t.position.opened_ts else None,
            "closed": t.position.closed_ts.isoformat() if t.position.closed_ts else None,
            "reason": t.reason,
            "pnl_usd": round(t.pnl_usd, 2),
        })
    return res


def run_portfolio_backtest(
    cfg: StrategyConfig,
    source: CandleSource,
    symbols: list[str],
    tf: Timeframe,
    bars: int = 2000,
    deposit_usd: float = 1000.0,
) -> dict[str, BacktestResult]:
    """Per-symbol backtests sharing config (slot/kill-switch interplay across
    symbols is exercised in the integrated paper loop; this gives per-coin
    strategy quality numbers for the Track 2 spec)."""
    return {
        s: run_backtest(cfg, source, s, tf, bars=bars, deposit_usd=deposit_usd)
        for s in symbols
    }
