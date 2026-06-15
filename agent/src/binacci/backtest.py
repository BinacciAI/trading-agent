"""Event-driven backtester — runs the SAME orchestrator + execution engine
used live, bar by bar. No separate "backtest logic" to drift from prod.

Also powers Track 2: every generated strategy spec ships with a backtest
report computed by this engine, making the spec verifiably backtestable.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd

from . import indicators as _ind
from .config import StrategyConfig, Timeframe
from .data import CandleSource
from .execution import ExecutionEngine
from .indicators import to_dataframe
from .macro import MacroSnapshot
from .models import Candle
from .orchestrator import Orchestrator


#: Opt-in: precompute causal indicators once per run and slice per bar
#: (see indicators.prime_precompute). Default off; proven trade-identical by
#: tests/test_fastind.py. Monkeypatchable in tests.
FAST_BACKTEST: bool = os.environ.get("BINACCI_FAST_BACKTEST", "0").strip().lower() in ("1", "true", "yes", "on")


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
        import math

        def fin(x: float, cap: float = 999.99) -> float:
            # JSON has no inf/nan — cap so the spec/API always serializes.
            if x is None or math.isnan(x):
                return 0.0
            if math.isinf(x):
                return cap if x > 0 else -cap
            return x

        return {
            "symbol": self.symbol, "timeframe": self.timeframe.value, "bars": self.bars,
            "trades": self.trades, "win_rate_pct": round(fin(self.win_rate_pct), 1),
            "total_pnl_usd": round(fin(self.total_pnl_usd), 2),
            "return_pct": round(fin(self.return_pct), 2),
            "max_drawdown_pct": round(fin(self.max_drawdown_pct), 2),
            "profit_factor": round(fin(self.profit_factor), 2),
            "sharpe": round(fin(self.sharpe), 2),
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
    ref_every: int = 1,
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
    max_window = max(400, warmup)
    # Precompute the full OHLCV frame ONCE. Each bar's window is a cheap iloc
    # view over it — identical rows to rebuilding from candle objects, but
    # without the per-bar DataFrame construction that otherwise dominates.
    full_df = to_dataframe(candles)

    # Opt-in fast path: compute causal indicators once over full_df and slice
    # per bar. Indicators are causal (value at bar i uses only bars <= i), so
    # this is lookahead-free; non-causal pivot/divergence detection stays
    # windowed. Cleared in `finally` so state never leaks across runs.
    primed = FAST_BACKTEST
    if primed:
        _ind.prime_precompute(full_df)
    try:
        for i in range(warmup, len(candles)):
            c = candles[i]
            lo = max(0, i + 1 - max_window)
            df = full_df.iloc[lo : i + 1]
            macro_idx["i"] = i

            # background sims refresh references. ref_every=1 (default) keeps the
            # exact per-bar model; the heavy universe sweep raises it to refresh
            # at the evaluation cadence (references are only ever read by
            # evaluate, so a matched cadence is a sound, much cheaper approx).
            if i % ref_every == 0:
                orch.update_references(symbol, tf, df)

            # entry evaluation (gates 1-4 + park level)
            if i % eval_every == 0:
                orch.evaluate(symbol, tf, df, ts=c.ts)

            # candle stream: fills, averaging, trailing, TP, kill switch
            prices = {symbol: c.close}
            orch.on_candle(symbol, tf, c, prices)

            snap = engine.snapshot(prices)
            equity.append(snap["equity_usd"])
    finally:
        if primed:
            _ind.clear_precompute()

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
            "strategy": t.position.meta.get("strategy", "reaction"),
            "market": t.position.meta.get("market", "spot"),
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


def run_universe_backtest(
    cfg: StrategyConfig,
    source: CandleSource,
    symbols: list[str],
    tf: Timeframe,
    bars: int = 600,
    deposit_usd: float = 1000.0,
    eval_every: int = 1,
) -> dict:
    """Backtest the WHOLE universe on one source and aggregate it. Each
    symbol is run with its own deposit (independent books); symbols whose
    source returns too little data are skipped, not fatal — so this works on
    CMC historical (plan-gated), the agent's accumulated 1m checkpoints, or
    synthetic alike. Returns per-symbol summaries + a portfolio roll-up."""
    results: list[BacktestResult] = []
    skipped: list[str] = []
    for s in symbols:
        try:
            results.append(run_backtest(cfg, source, s, tf, bars=bars,
                                        deposit_usd=deposit_usd, eval_every=eval_every))
        except Exception:
            skipped.append(s)
    trades = sum(r.trades for r in results)
    wins = sum(r.wins for r in results)
    total_pnl = sum(r.total_pnl_usd for r in results)
    worst_dd = max((r.max_drawdown_pct for r in results), default=0.0)
    per = [r.summary() for r in results]
    per.sort(key=lambda x: x["total_pnl_usd"], reverse=True)
    return {
        "timeframe": tf.value,
        "markets_tested": len(results),
        "markets_skipped": skipped,
        "deposit_usd_per_market": deposit_usd,
        "trades": trades,
        "win_rate_pct": round(wins / trades * 100, 1) if trades else 0.0,
        "total_pnl_usd": round(total_pnl, 2),
        "avg_return_pct_per_market": round(
            sum(r.return_pct for r in results) / len(results), 3) if results else 0.0,
        "winners": sum(1 for r in results if r.total_pnl_usd > 0),
        "losers": sum(1 for r in results if r.total_pnl_usd <= 0),
        "per_symbol": per,
    }


# --------------------------------------------------------------------------
# Full-universe, multi-timeframe, per-strategy/per-market backtest
# --------------------------------------------------------------------------

def _accumulate(bucket: dict, key: str, pnl: float) -> None:
    """Fold one trade pnl into a named bucket (count / wins / pnl)."""
    b = bucket.setdefault(key, {"trades": 0, "wins": 0, "pnl_usd": 0.0})
    b["trades"] += 1
    b["wins"] += 1 if pnl > 0 else 0
    b["pnl_usd"] += pnl


def _finalize(bucket: dict) -> dict:
    """Round + derive win-rate for each group, sorted by pnl desc."""
    out = {}
    for k, b in bucket.items():
        t = b["trades"]
        out[k] = {
            "trades": t,
            "win_rate_pct": round(b["wins"] / t * 100, 1) if t else 0.0,
            "total_pnl_usd": round(b["pnl_usd"], 2),
            "avg_pnl_usd": round(b["pnl_usd"] / t, 4) if t else 0.0,
        }
    return dict(sorted(out.items(), key=lambda kv: kv[1]["total_pnl_usd"], reverse=True))


def _run_one(task):
    """Top-level (picklable) worker: run one (symbol, timeframe) backtest.

    Returns (symbol, tf, result_or_None, error_or_None) so failures are data,
    not exceptions — the sweep skips them exactly like the serial path did.
    """
    run_cfg, source, s, tf, bars, deposit_usd, eval_every, ref_every = task
    try:
        r = run_backtest(run_cfg, source, s, tf, bars=bars,
                         deposit_usd=deposit_usd, eval_every=eval_every,
                         ref_every=ref_every)
        return (s, tf, r, None)
    except Exception as exc:  # insufficient data / source gap
        return (s, tf, None, str(exc)[:80])


def _resolve_workers(workers: Optional[int], n_tasks: int) -> int:
    """Default to serial (1) — identical to the original behaviour — unless the
    caller or BINACCI_BACKTEST_WORKERS opts in. Capped at task count and cores."""
    import os
    if workers is None:
        env = os.environ.get("BINACCI_BACKTEST_WORKERS", "").strip()
        workers = int(env) if env.lstrip("-").isdigit() else 1
    workers = max(1, int(workers))
    if workers > 1:
        workers = min(workers, max(1, n_tasks), (os.cpu_count() or 1))
    return workers


def run_full_backtest(
    cfg: StrategyConfig,
    source: CandleSource,
    symbols: Optional[list[str]] = None,
    timeframes: Optional[list[Timeframe]] = None,
    bars: int = 1500,
    deposit_usd: float = 1000.0,
    eval_every: int = 1,
    ref_every: Optional[int] = None,
    risk_mode: Optional[str] = None,
    progress: Optional[callable] = None,
    workers: Optional[int] = None,
) -> dict:
    """Backtest the ENTIRE universe across MULTIPLE timeframes and break the
    results down by strategy and by book (spot vs perp), with the time basis
    of the run attached.

    * ``symbols`` defaults to every market in ``cfg.symbols`` (all 146).
    * ``timeframes`` defaults to ``cfg.entry_timeframes``.
    * ``risk_mode`` (if given) is applied to a COPY of cfg so leverage/sizing
      match the chosen mode without mutating the caller's config.
    * Symbols/timeframes with too little data are skipped, never fatal — so it
      runs the same on synthetic, CMC historical, or live checkpoints.

    Returns a structured report: a portfolio roll-up, plus per-timeframe,
    per-strategy, per-market, per-symbol, and time-basis sections.
    """
    from .timebase import timebasis_row, timebasis_table

    run_cfg = cfg.model_copy(deep=True)
    if risk_mode:
        run_cfg.apply_risk_mode(risk_mode)
    # references are only read by evaluate, so for the heavy sweep refresh them
    # at the eval cadence (huge speedup); callers can override.
    ref_every = eval_every if ref_every is None else max(1, int(ref_every))

    syms = list(symbols) if symbols is not None else list(run_cfg.symbols)
    tfs = list(timeframes) if timeframes is not None else list(run_cfg.entry_timeframes)
    tfs = sorted(tfs, key=lambda t: t.minutes)

    results: list[BacktestResult] = []
    skipped: list[dict] = []
    by_strategy: dict = {}
    by_market: dict = {}
    by_tf: dict = {tf.value: {"trades": 0, "wins": 0, "pnl_usd": 0.0,
                              "markets": 0, "timebasis": timebasis_row(bars, tf)}
                   for tf in tfs}
    per_symbol: dict = {}  # symbol -> aggregated across timeframes

    total_runs = len(syms) * len(tfs)
    tasks = [(run_cfg, source, s, tf, bars, deposit_usd, eval_every, ref_every)
             for tf in tfs for s in syms]

    # Optional process-level parallelism for the heavy universe sweep. Runs are
    # fully independent, and aggregation below is order-independent (it iterates
    # `out` in task order), so the report is byte-identical regardless of worker
    # count. Any failure — unpicklable source, restricted/single-core env —
    # transparently falls back to the serial path.
    n_workers = _resolve_workers(workers, len(tasks))
    out: list = []
    if n_workers > 1 and len(tasks) > 1:
        try:
            from concurrent.futures import ProcessPoolExecutor
            with ProcessPoolExecutor(max_workers=n_workers) as ex:
                for k, triple in enumerate(ex.map(_run_one, tasks), start=1):
                    out.append(triple)
                    if progress and (k % 10 == 0 or k == total_runs):
                        progress(k, total_runs)
        except Exception:
            out = []  # serial fallback below
    if not out:
        for k, task in enumerate(tasks, start=1):
            out.append(_run_one(task))
            if progress and (k % 10 == 0 or k == total_runs):
                progress(k, total_runs)

    # Deterministic aggregation — identical to the original inline loop, but fed
    # from `out` (so it doesn't matter whether runs executed serially or across
    # processes).
    for (s, tf, r, err) in out:
        if r is None:
            skipped.append({"symbol": s, "tf": tf.value, "why": err or "no result"})
            continue
        results.append(r)
        by_tf[tf.value]["markets"] += 1
        ps = per_symbol.setdefault(s, {"trades": 0, "wins": 0, "pnl_usd": 0.0})
        for t in r.trade_log:
            pnl = t["pnl_usd"]
            _accumulate(by_strategy, t["strategy"], pnl)
            _accumulate(by_market, t.get("market", "spot"), pnl)
            by_tf[tf.value]["trades"] += 1
            by_tf[tf.value]["wins"] += 1 if pnl > 0 else 0
            by_tf[tf.value]["pnl_usd"] += pnl
            ps["trades"] += 1
            ps["wins"] += 1 if pnl > 0 else 0
            ps["pnl_usd"] += pnl

    trades = sum(r.trades for r in results)
    wins = sum(r.wins for r in results)
    total_pnl = sum(r.total_pnl_usd for r in results)
    worst_dd = max((r.max_drawdown_pct for r in results), default=0.0)

    # per-symbol roll-up (across all timeframes) -> finalize + rank
    sym_final = _finalize(per_symbol)
    ranked = list(sym_final.items())

    tf_final = {}
    for k, b in by_tf.items():
        t = b["trades"]
        tf_final[k] = {
            "markets_tested": b["markets"],
            "trades": t,
            "win_rate_pct": round(b["wins"] / t * 100, 1) if t else 0.0,
            "total_pnl_usd": round(b["pnl_usd"], 2),
            "timebasis": b["timebasis"],
        }

    return {
        "config": {
            "risk_mode": run_cfg.risk_mode.value,
            "perps_leverage": run_cfg.perps_leverage,
            "perps_target_mult": run_cfg.perps_target_mult,
            "bars_per_run": bars,
            "deposit_usd_per_run": deposit_usd,
            "markets_in_universe": len(syms),
            "timeframes": [tf.value for tf in tfs],
            "perp_strategies": sorted(run_cfg.perp_strategies),
        },
        "portfolio": {
            "runs_attempted": total_runs,
            "runs_completed": len(results),
            "runs_skipped": len(skipped),
            "trades": trades,
            "win_rate_pct": round(wins / trades * 100, 1) if trades else 0.0,
            "total_pnl_usd": round(total_pnl, 2),
            "avg_return_pct_per_run": round(
                sum(r.return_pct for r in results) / len(results), 3) if results else 0.0,
            "worst_drawdown_pct": round(worst_dd, 2),
            "winning_runs": sum(1 for r in results if r.total_pnl_usd > 0),
            "losing_runs": sum(1 for r in results if r.total_pnl_usd <= 0),
        },
        "by_timeframe": tf_final,
        "by_strategy": _finalize(by_strategy),
        "by_market": _finalize(by_market),
        "time_basis": timebasis_table(bars, tfs),
        "top_markets": [{"symbol": k, **v} for k, v in ranked[:15]],
        "bottom_markets": [{"symbol": k, **v} for k, v in ranked[-10:]] if len(ranked) > 15 else [],
        "skipped_sample": skipped[:20],
    }
