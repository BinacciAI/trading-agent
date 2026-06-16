"""FastAPI status server — feeds the dashboard and external monitors."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Optional

from .config import RuntimeConfig, StrategyConfig, Timeframe
from .data import SyntheticSource
from .execution import ExecutionEngine
from .orchestrator import Orchestrator

log = logging.getLogger(__name__)


class AgentContext:
    """Runtime context shared by the API and the live loop."""

    def __init__(self):
        import os

        self.scfg = StrategyConfig.load()
        self.rcfg = RuntimeConfig()
        # Both-ways trading. Paper mode SIMULATES on-chain perps (long+short),
        # the live perps venue trades both ways for real; only spot (pancake)
        # is long-only. Override with BINACCI_ALLOW_SHORTS=true|false.
        shorts_env = os.environ.get("BINACCI_ALLOW_SHORTS")
        if shorts_env is not None:
            self.scfg.allow_shorts = shorts_env.strip().lower() in ("1", "true", "yes", "on")
        else:
            self.scfg.allow_shorts = self.rcfg.venue in ("paper", "perps")
        # persisted operator choices (risk mode / leverage / knobs) win over
        # env + defaults, so a redeploy never reverts the operator's settings.
        if os.environ.get("BINACCI_MIN_EDGE_GATE") is None and self.rcfg.venue != "paper":
            self.scfg.min_edge_gate = True  # real money: never trade fee-losing setups
        self._data_dir = os.environ.get("BINACCI_DATA_DIR", "/tmp/binacci-data")
        from .persistence import apply_operator_settings
        apply_operator_settings(self.scfg, self._data_dir)
        self.scfg.apply_size_env()  # fee-efficient sizing wins over preset/operator
        self.engine = ExecutionEngine(self.scfg, deposit_usd=self.rcfg.deposit_usd)
        self.engine._simulate_fees = os.environ.get("BINACCI_SIMULATE_FEES", "true").strip().lower() not in ("0", "false", "no", "off")
        self.orchestrator = Orchestrator(self.scfg, self.engine)
        from .live import LiveLoop

        self.loop = LiveLoop(self.scfg, self.rcfg, self.engine, self.orchestrator)

    @property
    def prices(self) -> dict[str, float]:
        return self.loop.prices


_ctx: Optional[AgentContext] = None


def get_context() -> AgentContext:
    global _ctx
    if _ctx is None:
        _ctx = AgentContext()
    return _ctx


#: cache for the heavy universe backtest: key -> (ts, result)
_UNIVERSE_CACHE: dict = {}
#: cache for the full-universe (all-146 × multi-TF) backtest: key -> (ts, result)
_FULL_CACHE: dict = {}
#: in-flight full-backtest jobs: key -> {status, progress, total, result, error, started}
_FULL_JOBS: dict = {}


def _initial_workers() -> int:
    import os
    v = os.environ.get("BINACCI_BACKTEST_WORKERS", "1").strip()
    try:
        return max(1, int(v))
    except ValueError:
        return 1


#: runtime backtest performance controls (wired from the Settings page).
_PERF: dict = {"backtest_workers": _initial_workers()}


def _backtest_fast_on() -> bool:
    """Live read of the precompute flag (module global, not an import-time copy)."""
    import binacci.backtest as _bt
    return bool(_bt.FAST_BACKTEST)


def _explorer_tx_base(rcfg) -> str:
    """BscScan tx URL prefix — testnet-aware. Append a 0x… hash to link a trade."""
    return "https://testnet.bscscan.com/tx/" if rcfg.use_testnet else "https://bscscan.com/tx/"


def _default_source() -> str:
    """Default backtest data source (BINACCI_BACKTEST_SOURCE), e.g. set
    'cmc' on Railway where the CMC key + OHLCV plan exist."""
    import os
    return os.environ.get("BINACCI_BACKTEST_SOURCE", "synthetic")


def _book_split(ctx) -> dict:
    """Live spot vs perps breakdown — Binacci runs both books at once."""
    mkt = ctx.scfg.market_for
    out = {"spot": {"open": 0, "long": 0, "short": 0, "realized": 0.0},
           "perp": {"open": 0, "long": 0, "short": 0, "realized": 0.0}}
    for p in ctx.engine.open_positions():
        b = out[mkt(p.meta.get("strategy", "reaction"))]
        b["open"] += 1
        b["long" if p.side.value == "long" else "short"] += 1
    for t in ctx.engine.closed:
        b = out[mkt(t.position.meta.get("strategy", "reaction"))]
        b["realized"] += t.pnl_usd
    for b in out.values():
        b["realized"] = round(b["realized"], 2)
    return out


def build_app():
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware

    ctx = get_context()

    @asynccontextmanager
    async def lifespan(app):
        task = asyncio.create_task(ctx.loop.run())
        log.info("agent app started (live loop %s)",
                 "enabled" if ctx.rcfg.cmc_api_key else "idle — no CMC key")
        yield
        task.cancel()

    app = FastAPI(title="Binacci Agent", version="0.2.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware, allow_origins=["*"], allow_methods=["GET", "POST"], allow_headers=["*"],
    )

    @app.get("/health")
    def health():
        return {"ok": True, "venue": ctx.rcfg.venue, "testnet": ctx.rcfg.use_testnet,
                "loop_running": ctx.loop.running}

    @app.get("/status")
    def status():
        snap = ctx.engine.snapshot(ctx.prices)
        snap["loop"] = ctx.loop.status()
        snap["venue"] = ctx.rcfg.venue
        snap["allow_shorts"] = ctx.scfg.allow_shorts
        snap["trade_mode"] = "spot+perps"
        snap["books"] = _book_split(ctx)
        snap["regime"] = ctx.orchestrator.last_regime
        snap["regime_weighting"] = ctx.scfg.regime_weighting
        snap["prices"] = {k: round(v, 6) for k, v in ctx.prices.items()}
        snap["explorer_tx_base"] = _explorer_tx_base(ctx.rcfg)
        return snap

    @app.get("/positions")
    def positions():
        out = []
        for p in ctx.engine.open_positions():
            px = ctx.prices.get(p.symbol, p.avg_entry)
            out.append({
                "symbol": p.symbol, "tf": p.timeframe.value, "side": p.side.value,
                "market": ctx.scfg.market_for(p.meta.get("strategy", "reaction")),
                "leverage": p.meta.get("leverage", 1),
                "strategy": p.meta.get("strategy", "reaction"),
                "level_kind": p.meta.get("level_kind", ""),
                "state": p.state.value, "avg_entry": p.avg_entry,
                "mark": round(px, 6),
                "qty": p.qty, "notional_usd": p.notional_usd,
                "gain_pct": round(p.gain_pct(px), 3),
                "unrealized_pnl_usd": round(p.unrealized_pnl_usd(px), 2),
                "peak_gain_pct": round(p.peak_gain_pct, 3),
                "stop_pct": p.stop_pct, "target_pct": p.target_pct,
                "averaging_done": p.averaging_done,
                "opened": p.opened_ts.isoformat() if p.opened_ts else None,
                "open_tx": p.meta.get("venue_tx", ""),
            })
        return out

    @app.get("/trades")
    def trades():
        out = []
        for t in ctx.engine.closed:
            pos = t.position
            exit_fill = next((f for f in reversed(pos.fills) if f.tag == "exit"), None)
            exit_px = (exit_fill.price if exit_fill else 0.0) or pos.meta.get("venue_close_fill", 0.0)
            notional = pos.notional_usd
            held = ((pos.closed_ts - pos.opened_ts).total_seconds()
                    if pos.closed_ts and pos.opened_ts else None)
            out.append({
                "symbol": pos.symbol, "tf": pos.timeframe.value,
                "strategy": pos.meta.get("strategy", "reaction"),
                "side": pos.side.value,
                "market": ctx.scfg.market_for(pos.meta.get("strategy", "reaction")),
                "entry": round(pos.avg_entry, 6), "exit": round(exit_px, 6),
                "notional_usd": round(notional, 2),
                "leverage": pos.meta.get("leverage", 1),
                "pnl_usd": round(t.pnl_usd, 2),
                "gross_pnl_usd": round(t.gross_pnl_usd, 4),
                "fees_usd": round(t.fees_usd, 4),
                "pnl_pct": round((t.pnl_usd / notional * 100) if notional else 0.0, 3),
                "reason": t.reason,
                "opened": pos.opened_ts.isoformat() if pos.opened_ts else None,
                "closed": pos.closed_ts.isoformat() if pos.closed_ts else None,
                "held_s": round(held) if held is not None else None,
                "open_tx": pos.meta.get("venue_tx", ""),
                "close_tx": pos.meta.get("venue_close_tx", ""),
            })
        return out

    @app.get("/traces")
    def traces(limit: int = 50):
        out = []
        for tr in ctx.orchestrator.traces[-limit:]:
            out.append({
                "symbol": tr.symbol, "tf": tr.timeframe.value, "ts": tr.ts.isoformat(),
                "strategy": tr.strategy, "entered": tr.entered,
                "gates": [{"step": g.step.value, "passed": g.passed, "detail": g.detail}
                          for g in tr.gates],
            })
        return out

    @app.get("/config")
    def config():
        """Operational settings for the Settings page (no secrets)."""
        from .config import RiskMode

        return {
            "venue": ctx.rcfg.venue,
            "use_testnet": ctx.rcfg.use_testnet,
            "deposit_usd": ctx.rcfg.deposit_usd,
            "poll_seconds": ctx.rcfg.poll_seconds,
            "macro_refresh_seconds": ctx.rcfg.macro_refresh_seconds,
            "fear_greed_refresh_seconds": ctx.rcfg.fear_greed_refresh_seconds,
            "poll_only_verified": ctx.rcfg.poll_only_verified,
            "warmup_backfill": ctx.rcfg.warmup_backfill,
            "quote": ctx.scfg.quote,
            "live_timeframes": [tf.value for tf in ctx.loop.live_tfs],
            "trade_mode": "spot+perps",
            "allow_shorts": ctx.scfg.allow_shorts,
            "perps_leverage": ctx.scfg.perps_leverage,
            "perps_target_mult": ctx.scfg.perps_target_mult,
            "min_signal_strength": ctx.scfg.min_signal_strength,
            "regime_weighting": ctx.scfg.regime_weighting,
            "min_edge_gate": ctx.scfg.min_edge_gate,
            "fees": __import__("binacci.fees", fromlist=["fee_model"]).fee_model().summary(
                ctx.rcfg.deposit_usd, ctx.scfg.margin.entry_pct_of_deposit, ctx.scfg.perps_leverage),
            "trailing": {"trigger": ctx.scfg.trailing.trigger_pct,
                         "initial": ctx.scfg.trailing.initial_sl_pct,
                         "step": ctx.scfg.trailing.step_pct},
            "trading_halted": ctx.engine.trading_halted,
            "halt_reason": ctx.engine.halt_reason,
            "perp_data_source": getattr(ctx.loop, "perp_data_source", "spot_quote"),
            "book_cap": ctx.scfg.book_cap(),
            "perp_strategies": sorted(ctx.scfg.perp_strategies),
            "spot_strategies": sorted(s.name for s in ctx.orchestrator.strategies
                                      if ctx.scfg.market_for(s.name) == "spot"),
            "risk": ctx.scfg.risk_summary(),
            "risk_modes": [m.value for m in RiskMode],
            "credits": ctx.loop.credit_estimate(),
            "cmc_key_set": bool(ctx.rcfg.cmc_api_key),
            "fast_backtest": _backtest_fast_on(),
            "backtest_workers": _PERF["backtest_workers"],
            "cpu_count": __import__("os").cpu_count() or 1,
        }

    @app.post("/risk/mode")
    def set_risk_mode(mode: str):
        """Switch the live risk preset (conservative|balanced|aggressive)."""
        from .config import RiskMode

        try:
            rm = RiskMode(mode.lower())
        except ValueError:
            return {"ok": False, "error": f"unknown mode {mode!r}",
                    "modes": [m.value for m in RiskMode]}
        ctx.scfg.apply_risk_mode(rm)  # ctx.engine.cfg is the same object
        ctx.scfg.apply_size_env()  # keep fee-efficient sizing across a mode switch
        ctx.scfg.export_runtime_env()  # propagate leverage to venue/brain/monitors
        from .persistence import save_operator_settings
        save_operator_settings(getattr(ctx, "_data_dir", "/tmp/binacci-data"),
                               {"risk_mode": rm.value, "perps_leverage": ctx.scfg.perps_leverage})
        return {"ok": True, "mode": rm.value, "risk": ctx.scfg.risk_summary(),
                "perps_leverage": ctx.scfg.perps_leverage,
                "perps_target_mult": ctx.scfg.perps_target_mult}

    @app.post("/control")
    def control(perps_leverage: Optional[float] = None, min_strength: Optional[float] = None,
                regime_weighting: Optional[bool] = None, perps_target_mult: Optional[float] = None,
                trail_trigger: Optional[float] = None, trail_initial: Optional[float] = None,
                trail_step: Optional[float] = None):
        """Operator console: apply risk/edge knobs to the LIVE config (the
        engine + orchestrator share this object, so changes take effect on the
        next evaluation). Leverage is also exported to the venue/brain env."""
        c = ctx.scfg
        applied: dict = {}
        if perps_leverage is not None:
            c.perps_leverage = max(1.0, float(perps_leverage)); applied["perps_leverage"] = c.perps_leverage
        if perps_target_mult is not None:
            c.perps_target_mult = max(1.0, float(perps_target_mult)); applied["perps_target_mult"] = c.perps_target_mult
        if min_strength is not None:
            c.min_signal_strength = max(0.0, min(1.0, float(min_strength))); applied["min_signal_strength"] = c.min_signal_strength
        if regime_weighting is not None:
            c.regime_weighting = bool(regime_weighting); applied["regime_weighting"] = c.regime_weighting
        if trail_trigger is not None:
            c.trailing.trigger_pct = max(0.0, float(trail_trigger)); applied["trail_trigger"] = c.trailing.trigger_pct
        if trail_initial is not None:
            c.trailing.initial_sl_pct = max(0.0, float(trail_initial)); applied["trail_initial"] = c.trailing.initial_sl_pct
        if trail_step is not None:
            c.trailing.step_pct = max(0.01, float(trail_step)); applied["trail_step"] = c.trailing.step_pct
        c.export_runtime_env()
        from .persistence import save_operator_settings
        save_operator_settings(getattr(ctx, "_data_dir", "/tmp/binacci-data"), {
            "perps_leverage": c.perps_leverage, "perps_target_mult": c.perps_target_mult,
            "min_signal_strength": c.min_signal_strength, "regime_weighting": c.regime_weighting,
            "trailing": {"trigger": c.trailing.trigger_pct, "initial": c.trailing.initial_sl_pct,
                         "step": c.trailing.step_pct}})
        return {"ok": True, "applied": applied, "live": {
            "perps_leverage": c.perps_leverage, "perps_target_mult": c.perps_target_mult,
            "min_signal_strength": c.min_signal_strength, "regime_weighting": c.regime_weighting,
            "trailing": {"trigger": c.trailing.trigger_pct, "initial": c.trailing.initial_sl_pct,
                         "step": c.trailing.step_pct}}}

    @app.post("/halt")
    def halt(reason: str = "operator stop"):
        """Operator stop: block NEW opens immediately. Existing positions keep
        being managed/closed (the book can always be flattened). Clear with
        POST /venue/resume."""
        ctx.engine.halt(reason)
        return {"trading_halted": ctx.engine.trading_halted, "halt_reason": ctx.engine.halt_reason}

    @app.get("/attribution")
    def attribution():
        """P/L attribution by strategy, book, and macro regime — realized
        (closed) + unrealized (open marks)."""
        eng = ctx.engine; mkt = ctx.scfg.market_for; prices = ctx.prices
        def row(): return {"trades": 0, "wins": 0, "realized": 0.0, "unrealized": 0.0, "open": 0}
        by_strategy: dict = {}; by_book = {"spot": row(), "perp": row()}; by_regime: dict = {}
        for t in eng.closed:
            sname = t.position.meta.get("strategy", "reaction")
            rg = t.position.meta.get("regime", "unknown")
            for d in (by_strategy.setdefault(sname, row()), by_book[mkt(sname)], by_regime.setdefault(rg, row())):
                d["trades"] += 1; d["wins"] += 1 if t.pnl_usd > 0 else 0; d["realized"] += t.pnl_usd
        for p in eng.open_positions():
            sname = p.meta.get("strategy", "reaction")
            rg = p.meta.get("regime", "unknown")
            u = p.unrealized_pnl_usd(prices.get(p.symbol, p.avg_entry))
            for d in (by_strategy.setdefault(sname, row()), by_book[mkt(sname)], by_regime.setdefault(rg, row())):
                d["unrealized"] += u; d["open"] += 1
        def fin(g):
            for d in g.values():
                d["realized"] = round(d["realized"], 2); d["unrealized"] = round(d["unrealized"], 2)
                d["net"] = round(d["realized"] + d["unrealized"], 2)
                d["win_rate"] = round(d["wins"] / d["trades"] * 100, 1) if d["trades"] else 0.0
            return g
        return {"regime": ctx.orchestrator.last_regime,
                "by_strategy": fin(by_strategy), "by_book": fin(by_book), "by_regime": fin(by_regime)}

    @app.get("/fees")
    def fees():
        """On-chain trading-cost model: PancakeSwap swap fees + on-chain perp
        fees/funding + BSC gas, the breakeven price move per book, and the
        realized fees the agent has already paid."""
        from .fees import fee_model
        fm = fee_model()
        paid = sum(t.fees_usd for t in ctx.engine.closed)
        gross = sum(t.gross_pnl_usd for t in ctx.engine.closed)
        net = sum(t.pnl_usd for t in ctx.engine.closed)
        margin = ctx.rcfg.deposit_usd * ctx.scfg.margin.entry_pct_of_deposit
        notional_perp = margin * ctx.scfg.perps_leverage
        return {
            "model": fm.summary(ctx.rcfg.deposit_usd, ctx.scfg.margin.entry_pct_of_deposit, ctx.scfg.perps_leverage),
            "simulate_fees": ctx.engine._simulate_fees,
            "min_edge_gate": ctx.scfg.min_edge_gate,
            "realized": {"gross_usd": round(gross, 2), "fees_usd": round(paid, 2), "net_usd": round(net, 2),
                         "fee_drag_pct_of_gross": round(paid / gross * 100, 1) if gross > 0 else None},
            "breakeven_move_pct_incl_gas": {
                "spot": round(__import__("binacci.routing", fromlist=["execution_router"]).execution_router().breakeven_move_pct("spot", margin, "BNB"), 3),
                "perp": round(__import__("binacci.routing", fromlist=["execution_router"]).execution_router().breakeven_move_pct("perp", notional_perp, "BNB"), 3),
            },
            "routing": __import__("binacci.routing", fromlist=["execution_router"]).execution_router().summary(ctx.rcfg.deposit_usd, ctx.scfg.margin.entry_pct_of_deposit, ctx.scfg.perps_leverage),
            "note": "Gas is a fixed $ per action, so it dominates on small notional. "
                    "Breakeven falls as deposit/position size rises.",
        }

    @app.post("/backtest/perf")
    def set_backtest_perf(fast_backtest: Optional[bool] = None,
                          workers: Optional[int] = None):
        """Wire the backtest performance controls from the Settings page.

        ``fast_backtest`` toggles the causal-indicator precompute
        (BINACCI_FAST_BACKTEST); ``workers`` sets the process count for the
        universe sweep (BINACCI_BACKTEST_WORKERS, capped at cpu_count). Both
        update the live module flag AND the env var, so serial in-process runs
        and spawned worker processes alike honour the change. Neither affects
        live trading or backtest results — only speed.
        """
        import os
        import binacci.backtest as _bt

        if fast_backtest is not None:
            _bt.FAST_BACKTEST = bool(fast_backtest)
            os.environ["BINACCI_FAST_BACKTEST"] = "1" if fast_backtest else "0"
        if workers is not None:
            w = max(1, min(int(workers), os.cpu_count() or 1))
            _PERF["backtest_workers"] = w
            os.environ["BINACCI_BACKTEST_WORKERS"] = str(w)
        return {"ok": True, "fast_backtest": bool(_bt.FAST_BACKTEST),
                "backtest_workers": _PERF["backtest_workers"],
                "cpu_count": os.cpu_count() or 1}

    @app.get("/backtest")
    def backtest(symbol: str = "BNB", timeframe: str = "15m",
                 strategy: str = "portfolio", bars: int = 800, source: str = ""):
        """On-demand verification backtest for the Backtests page.
        source: synthetic (default) | cmc | checkpoint/live."""
        from .backtest import run_backtest
        from .data import make_source
        from .skill import _config_for

        bars = max(300, min(int(bars), 1500))
        cfg = ctx.scfg if strategy == "portfolio" else _config_for(strategy, ctx.scfg)
        src_name = source or _default_source()
        used = src_name
        try:
            res = run_backtest(cfg, make_source(src_name, ctx.rcfg), symbol.upper(),
                               Timeframe(timeframe), bars=bars, deposit_usd=ctx.rcfg.deposit_usd)
        except Exception:
            if src_name == "synthetic":
                return {"error": "no data", "symbol": symbol.upper(), "timeframe": timeframe, "source": src_name}
            used = "synthetic"  # graceful fallback until real data has accumulated
            res = run_backtest(cfg, make_source("synthetic", ctx.rcfg), symbol.upper(),
                               Timeframe(timeframe), bars=bars, deposit_usd=ctx.rcfg.deposit_usd)
        out = res.summary()
        out["strategy"] = strategy
        out["source"] = used
        out["requested_source"] = src_name
        step = max(1, len(res.equity_curve) // 120)
        out["equity_curve"] = [round(x, 2) for x in res.equity_curve[::step]]
        return out

    @app.get("/portfolio-backtest")
    def portfolio_backtest(timeframe: str = "15m", bars: int = 500,
                           limit: int = 12, source: str = ""):
        """Backtest the WHOLE BNB universe and aggregate. Cached 10 min
        because it is heavy. source: synthetic | cmc | checkpoint/live."""
        from .backtest import run_universe_backtest
        from .data import make_source
        import time

        src_name = source or _default_source()
        symbols = ctx.scfg.symbols[:max(1, min(int(limit), len(ctx.scfg.symbols)))]
        bars = max(300, min(int(bars), 1200))
        key = (src_name, timeframe, bars, len(symbols), ctx.scfg.risk_mode.value)
        now = time.time()
        hit = _UNIVERSE_CACHE.get(key)
        if hit and now - hit[0] < 600:
            return {**hit[1], "cached": True}
        res = run_universe_backtest(ctx.scfg, make_source(src_name, ctx.rcfg), symbols,
                                    Timeframe(timeframe), bars=bars,
                                    deposit_usd=ctx.rcfg.deposit_usd, eval_every=2)
        used = src_name
        if res["markets_tested"] == 0 and src_name != "synthetic":
            used = "synthetic"  # real data not accumulated yet -> show synthetic
            res = run_universe_backtest(ctx.scfg, make_source("synthetic", ctx.rcfg), symbols,
                                        Timeframe(timeframe), bars=bars,
                                        deposit_usd=ctx.rcfg.deposit_usd, eval_every=2)
        res["source"] = used
        res["requested_source"] = src_name
        res["universe_size"] = len(ctx.scfg.symbols)
        _UNIVERSE_CACHE[key] = (now, res)
        return {**res, "cached": False}

    @app.get("/full-backtest")
    def full_backtest(timeframes: str = "15m,4h,1d", bars: int = 800,
                      limit: int = 0, source: str = "", risk_mode: str = "",
                      eval_every: int = 3):
        """ALL-universe (up to 146 markets) × MULTI-timeframe backtest with
        per-strategy, per-market (spot/perp) and per-timeframe breakdowns plus
        the wall-clock time basis of the run.

        Runs as a BACKGROUND JOB so a 146×multi-TF sweep never blocks the event
        loop or times out the request: the first call starts the job and returns
        ``{status: "running", progress, total}``; the dashboard polls the same
        URL until ``status`` is ``"done"`` (result inlined) or ``"error"``.
        Results are cached 15 min. ``limit`` (>0) caps markets; ``risk_mode``
        picks the leverage tier. source: synthetic | cmc | checkpoint/live."""
        from .backtest import run_full_backtest
        from .data import make_source
        import time, threading

        src_name = source or _default_source()
        try:
            tfs = [Timeframe(t.strip()) for t in timeframes.split(",") if t.strip()]
        except ValueError as exc:
            return {"status": "error", "error": f"bad timeframe: {exc}"}
        if not tfs:
            return {"status": "error", "error": "no timeframes given"}
        bars = max(300, min(int(bars), 1500))
        syms = ctx.scfg.symbols if limit <= 0 else ctx.scfg.symbols[:int(limit)]
        rm = risk_mode.lower() or ctx.scfg.risk_mode.value
        eval_every = max(1, int(eval_every))
        key = (src_name, tuple(t.value for t in tfs), bars, len(syms), rm, eval_every)
        now = time.time()

        hit = _FULL_CACHE.get(key)
        if hit and now - hit[0] < 900:
            return {"status": "done", **hit[1], "cached": True}

        job = _FULL_JOBS.get(key)
        if job:
            if job["status"] == "running":
                return {"status": "running", "progress": job["progress"],
                        "total": job["total"], "elapsed_s": round(now - job["started"], 1)}
            if job["status"] == "error":
                _FULL_JOBS.pop(key, None)
                return {"status": "error", "error": job["error"]}
            if job["status"] == "done":  # hand result over to the cache
                _FULL_CACHE[key] = (now, job["result"])
                _FULL_JOBS.pop(key, None)
                return {"status": "done", **job["result"], "cached": False}

        state = {"status": "running", "progress": 0, "total": len(syms) * len(tfs),
                 "result": None, "error": None, "started": now}
        _FULL_JOBS[key] = state

        def _run():
            try:
                def prog(done, total):
                    state["progress"] = done
                    state["total"] = total
                res = run_full_backtest(
                    ctx.scfg, make_source(src_name, ctx.rcfg), symbols=syms,
                    timeframes=tfs, bars=bars, deposit_usd=ctx.rcfg.deposit_usd,
                    eval_every=eval_every, risk_mode=rm, progress=prog,
                    workers=_PERF["backtest_workers"])
                used = src_name
                if res["portfolio"]["runs_completed"] == 0 and src_name != "synthetic":
                    used = "synthetic"  # real data not accumulated yet
                    res = run_full_backtest(
                        ctx.scfg, make_source("synthetic", ctx.rcfg), symbols=syms,
                        timeframes=tfs, bars=bars, deposit_usd=ctx.rcfg.deposit_usd,
                        eval_every=eval_every, risk_mode=rm, progress=prog,
                        workers=_PERF["backtest_workers"])
                res["source"] = used
                res["requested_source"] = src_name
                state["result"] = res
                state["status"] = "done"
            except Exception as exc:  # surface the reason instead of a dead 500
                log.exception("full-backtest job failed")
                state["error"] = str(exc)[:200]
                state["status"] = "error"

        threading.Thread(target=_run, name="full-backtest", daemon=True).start()
        return {"status": "running", "progress": 0, "total": state["total"], "elapsed_s": 0.0}


    @app.get("/timebasis")
    def timebasis(bars: int = 1500, timeframes: str = ""):
        """Wall-clock span that a candle COUNT represents on each timeframe —
        e.g. 1500 bars is ~15.6 days on 15m but ~4.1 years on 1d. Drives the
        time-basis visual so bar counts are never shown without their meaning."""
        from .timebase import timebasis_table

        tfs = ([Timeframe(t.strip()) for t in timeframes.split(",") if t.strip()]
               or None)
        return {"bars": int(bars), "rows": timebasis_table(int(bars), tfs)}

    @app.get("/strategies")
    def strategies():
        """The active strategy portfolio and per-strategy live stats."""
        from .skill import strategy_catalog

        names = [s.name for s in ctx.orchestrator.strategies]
        open_by: dict[str, int] = {}
        pnl_by: dict[str, float] = {}
        for p in ctx.engine.open_positions():
            k = p.meta.get("strategy", "reaction")
            open_by[k] = open_by.get(k, 0) + 1
        for t in ctx.engine.closed:
            k = t.position.meta.get("strategy", "reaction")
            pnl_by[k] = round(pnl_by.get(k, 0.0) + t.pnl_usd, 2)
        return {
            "active": names,
            "catalog": strategy_catalog(),
            "open_positions_by_strategy": open_by,
            "realized_pnl_by_strategy": pnl_by,
        }

    @app.get("/spec")
    def spec(symbol: str = "BNB", timeframe: str = "4h", strategy: str = "reaction"):
        from .skill import generate_portfolio_spec, generate_strategy_spec

        if strategy == "portfolio":
            return generate_portfolio_spec(
                ctx.scfg, symbol=symbol.upper(), tf=Timeframe(timeframe),
                source=SyntheticSource())
        return generate_strategy_spec(
            ctx.scfg, symbol=symbol.upper(), tf=Timeframe(timeframe),
            source=SyntheticSource(), strategy=strategy,
        )

    @app.get("/manifest")
    def manifest(strategy: str = "reaction"):
        from .skill import skill_manifest

        return skill_manifest(strategy)

    @app.get("/manifests")
    def manifests():
        from .regime import regime_skill_manifest
        from .skill import all_skill_manifests

        return all_skill_manifests() + [regime_skill_manifest()]

    @app.get("/signals")
    def signals():
        """Pending limit entries — levels parked awaiting a touch."""
        return [{
            "symbol": p.signal.symbol, "tf": p.signal.timeframe.value,
            "side": p.signal.side.value, "strategy": p.signal.strategy,
            "level_price": p.signal.level_price,
            "target_pct": p.signal.target_pct,
            "level_kind": p.signal.meta.get("level_kind", ""),
            "created": p.created.isoformat(), "expires": p.expires.isoformat(),
        } for p in ctx.orchestrator.pending]

    @app.get("/references")
    def references():
        """Market Memory — current reference points per symbol/timeframe."""
        out = []
        for (sym, tf), ref in sorted(ctx.orchestrator.book.refs.items()):
            out.append({
                "symbol": sym, "tf": tf.value, "kind": ref.kind.value,
                "price": ref.price, "ts": ref.ts.isoformat(), "clean": ref.clean,
                "rsi": ref.meta.get("rsi"), "volume_ratio": ref.meta.get("volume_ratio"),
            })
        return out

    @app.get("/venue")
    def venue():
        return {
            "venue": ctx.rcfg.venue,
            "testnet": ctx.rcfg.use_testnet,
            "wallet": ctx.rcfg.wallet_address,
            "explorer_tx_base": _explorer_tx_base(ctx.rcfg),
            "preflight_ok": ctx.loop.preflight_ok,
            "preflight_detail": ctx.loop.preflight_detail,
            "trading_halted": ctx.engine.trading_halted,
            "halt_reason": ctx.engine.halt_reason,
            "reconcile_state": ctx.loop.reconcile_state,
            "reconcile_detail": ctx.loop.reconcile_detail,
            "onchain_balance_usd": ctx.loop.onchain_balance_usd,
            "mev_protect": ctx.rcfg.mev_protect,
            "confirm_receipts": ctx.rcfg.confirm_receipts,
            "log": ctx.loop.venue_log[-50:],
        }

    @app.post("/venue/preflight")
    def venue_preflight():
        """Re-run venue preflight (wallet/auth/net). Halts on failure."""
        ok = ctx.loop.run_preflight()
        return {"preflight_ok": ok, "detail": ctx.loop.preflight_detail,
                "trading_halted": ctx.engine.trading_halted}

    @app.post("/venue/reconcile/ack")
    def venue_reconcile_ack():
        """Human ack that restored positions match the chain — clears the boot halt."""
        return ctx.loop.ack_reconcile()

    @app.post("/venue/resume")
    def venue_resume():
        """Clear a trading halt (preflight/desync) after the operator resolves it."""
        ctx.engine.resume()
        return {"trading_halted": ctx.engine.trading_halted, "halt_reason": ctx.engine.halt_reason}

    @app.get("/x402")
    def x402_info():
        """x402 monetization descriptor (L1 optional layer)."""
        return {
            "protocol": "x402",
            "status": "free_during_hackathon",
            "paid_rails": {
                "apex": {"endpoint": "/apex", "standard": "ERC-8183",
                         "escrow": "UMA OOv3 verified", "network": "bsc"},
                "x402": {"planned_assets": ["USDT (bsc, 18dp)", "USDC (bsc, 6dp)"],
                         "transfer_methods": ["eip3009", "permit2-exact"],
                         "pay_to": ctx.rcfg.wallet_address or "set BINACCI_WALLET_ADDRESS"},
            },
            "resource": {"url": "/spec", "description": "Backtestable strategy spec",
                         "mimeType": "application/json"},
        }

    @app.get("/chain")
    def chain():
        """BNB AI Agent SDK status — ERC-8004 identity + APEX commerce."""
        import importlib.util, json, os
        from pathlib import Path

        have = importlib.util.find_spec("bnbagent") is not None
        marker = Path(os.environ.get("BINACCI_DATA_DIR", "/tmp/binacci-data")) / "erc8004.json"
        reg = None
        if marker.exists():
            try:
                reg = json.loads(marker.read_text())
            except Exception:
                reg = None
        return {
            "sdk": "bnbagent (BNB AI Agent SDK)",
            "installed": have,
            "network": "bsc-testnet" if ctx.rcfg.use_testnet else "bsc",
            "erc8004": {
                "registered": bool(reg),
                "agent_id": (reg or {}).get("agentId"),
                "tx": (reg or {}).get("tx"),
                "auto_register": os.environ.get("BINACCI_AUTO_REGISTER", "").lower() in ("1", "true", "yes"),
            },
            "apex": {
                "standard": "ERC-8183",
                "mounted": have,
                "job_endpoint": "/apex/job/execute",
                "deliverable": "backtestable strategy spec (Track-2 skill output)",
            },
            "wallet": ctx.rcfg.wallet_address or None,
        }

    @app.get("/compete")
    def compete():
        """Track-1 competition status: contract + on-chain registration."""
        from .venues import TwakCLI

        twak = TwakCLI()
        status = {}
        if twak.installed:
            try:
                status = twak.compete_status()
            except Exception as e:
                status = {"error": str(e)[:200]}
        return {
            "track": 1,
            "contract": ctx.rcfg.competition_contract,
            "explorer": f"https://bsctrace.com/address/{ctx.rcfg.competition_contract}",
            "wallet": ctx.rcfg.wallet_address or None,
            "twak_installed": twak.installed,
            "registration": status,
        }

    @app.post("/compete/register")
    def compete_register():
        """Register the agent on-chain for the Track-1 live competition."""
        from .venues import TwakCLI

        twak = TwakCLI()
        if not twak.installed:
            return {"ok": False, "error": "twak CLI not installed"}
        res = twak.compete_register()
        ok = not bool(res.get("error"))
        return {"ok": ok, "contract": ctx.rcfg.competition_contract, "result": res}

    @app.get("/competition")
    def competition():
        """Track-1 competition readiness: registration, the 1-trade/day rule,
        eligible-token coverage, and live-venue status."""
        from datetime import datetime, timezone
        from .venues import TwakCLI

        now = datetime.now(timezone.utc)
        today = now.date()
        closed = ctx.engine.closed
        trades_today = sum(1 for t in closed
                           if t.position.closed_ts and t.position.closed_ts.date() == today)
        opens_today = sum(1 for p in ctx.engine.positions
                          if p.opened_ts and p.opened_ts.date() == today)
        traded_syms = sorted({t.position.symbol for t in closed}
                             | {p.symbol for p in ctx.engine.open_positions()})
        twak = TwakCLI()
        reg = {}
        if twak.installed:
            try:
                reg = twak.compete_status()
            except Exception as e:
                reg = {"error": str(e)[:160]}
        registered = bool(reg.get("registered") or reg.get("agentAddress") or reg.get("address"))
        return {
            "track": 1,
            "contract": ctx.rcfg.competition_contract,
            "explorer": f"https://bsctrace.com/address/{ctx.rcfg.competition_contract}",
            "wallet": ctx.rcfg.wallet_address or None,
            "registered": registered,
            "registration": reg,
            "twak_installed": twak.installed,
            "eligible_tokens": len(ctx.scfg.symbols),
            "markets_active": ctx.loop.status().get("markets", len(ctx.scfg.symbols)),
            "min_trades_per_day": 1,
            "trades_today": trades_today,
            "opens_today": opens_today,
            "activity_today": trades_today + opens_today,
            "min_trade_met": (trades_today + opens_today) >= 1,
            "total_trades": len(closed),
            "symbols_traded": traded_syms[:60],
            "venue": ctx.rcfg.venue,
            "testnet": ctx.rcfg.use_testnet,
            "live_trading": ctx.rcfg.venue != "paper" and not ctx.rcfg.use_testnet,
        }

    @app.get("/memory")
    def memory():
        """Binacci's brain — structured memory snapshot."""
        from .brain import lessons, per_strategy_stats

        snap = ctx.engine.snapshot(ctx.prices)
        refs = []
        book = getattr(ctx.orchestrator, "book", None)
        if book is not None:
            for (sym, tf), r in sorted(book.refs.items())[:60]:
                refs.append({"symbol": sym, "tf": tf.value, "kind": r.kind.value,
                             "price": r.price, "ts": r.ts.isoformat(), "clean": r.clean})
        bars = {s: len(b.bars) for s, b in ctx.loop.builders.items()}
        return {
            "identity": "Binacci — autonomous BNB trading agent. Brains separated from hands; "
                        "nothing is ever forgotten.",
            "equity_usd": snap["equity_usd"], "realized_pnl_usd": snap["realized_pnl_usd"],
            "open_positions": snap["slots_used"], "closed_trades": snap["closed_trades"],
            "per_strategy": per_strategy_stats(ctx.engine),
            "lessons": lessons(ctx.engine),
            "references": refs,
            "chart_memory": {"symbols_with_data": sum(1 for v in bars.values() if v),
                             "max_bars": max(bars.values()) if bars else 0,
                             "retention_bars": __import__("binacci.live", fromlist=["MAX_1M_BARS"]).MAX_1M_BARS},
        }

    @app.get("/memory/md")
    def memory_md():
        """The living MEMORY.md the agent writes about itself."""
        import os
        from pathlib import Path

        from fastapi.responses import PlainTextResponse
        from .brain import build_memory_md

        p = Path(os.environ.get("BINACCI_DATA_DIR", "/tmp/binacci-data")) / "MEMORY.md"
        if p.exists():
            return PlainTextResponse(p.read_text(encoding="utf-8"))
        return PlainTextResponse(build_memory_md(ctx.loop))

    @app.post("/optimize")
    def optimize_start():
        """Meta-learner: run the fee-aware sweep on accumulated data and propose
        the best risk-adjusted edge config. Non-blocking; poll GET /optimize."""
        from .metalearn import start_job
        syms = list(ctx.scfg.symbols)[:8]
        return start_job(ctx.scfg, ctx.rcfg, syms, getattr(ctx, "_data_dir", "/tmp/binacci-data"))

    @app.get("/optimize")
    def optimize_status():
        from .metalearn import last_proposal
        return last_proposal(getattr(ctx, "_data_dir", "/tmp/binacci-data"))

    @app.post("/optimize/apply")
    def optimize_apply():
        """Apply the meta-learner's best proposal to the live engine (operator
        confirm) and persist it."""
        from .metalearn import last_proposal
        from .persistence import save_operator_settings
        prop = last_proposal(getattr(ctx, "_data_dir", "/tmp/binacci-data")).get("proposal") or {}
        best = prop.get("best")
        if not best:
            return {"ok": False, "error": "no proposal yet — run POST /optimize first"}
        c = ctx.scfg
        c.perps_leverage = max(1.0, float(best["perps_leverage"]))
        c.perps_target_mult = max(1.0, float(best["perps_target_mult"]))
        tr = best.get("trailing") or {}
        c.trailing.trigger_pct = float(tr.get("trigger", c.trailing.trigger_pct))
        c.trailing.initial_sl_pct = float(tr.get("initial", c.trailing.initial_sl_pct))
        c.trailing.step_pct = float(tr.get("step", c.trailing.step_pct))
        c.export_runtime_env()
        save_operator_settings(getattr(ctx, "_data_dir", "/tmp/binacci-data"), {
            "perps_leverage": c.perps_leverage, "perps_target_mult": c.perps_target_mult,
            "trailing": {"trigger": c.trailing.trigger_pct, "initial": c.trailing.initial_sl_pct, "step": c.trailing.step_pct}})
        return {"ok": True, "applied": best["label"], "perps_leverage": c.perps_leverage,
                "perps_target_mult": c.perps_target_mult,
                "trailing": {"trigger": c.trailing.trigger_pct, "initial": c.trailing.initial_sl_pct, "step": c.trailing.step_pct}}

    @app.get("/sentinel")
    def sentinel():
        """Market-anomaly safety net: de-peg / flash-crash / broad-crash status."""
        s = getattr(ctx.loop, "sentinel", None)
        if s is None:
            return {"armed": False}
        out = s.status()
        out["trading_halted"] = ctx.engine.trading_halted
        out["halt_reason"] = ctx.engine.halt_reason
        return out

    @app.get("/regime")
    def regime():
        """Macro Regime Classifier (CMC-data skill) — live classification."""
        from .regime import classify_regime, regime_skill_manifest

        macro = ctx.loop.macro
        fg = ctx.loop.fear_greed_value
        out = classify_regime(macro, fg)
        out["skill"] = regime_skill_manifest()["name"]
        return out

    @app.get("/funding")
    def funding():
        """Perps funding / basis monitor (CMC-data skill). Per-symbol perp
        premium vs spot and the fade classification. Empty in paper (mark==spot)."""
        from .funding import classify_funding, funding_skill_manifest
        book = {}
        try:
            book = dict(ctx.orchestrator.funding_provider() or {})
        except Exception:
            book = {}
        thr = ctx.scfg.funding.min_abs_funding_pct
        rows = [{"symbol": s, **classify_funding(f, thr)} for s, f in sorted(book.items())]
        return {"threshold_pct": thr, "count": len(rows),
                "extreme": [r for r in rows if r["extreme"]],
                "all": rows, "skill": funding_skill_manifest(),
                "note": "Funding from on-chain perp mark vs CMC spot; idle in paper."}

    @app.get("/basis")
    def basis():
        """Spot–perp basis carry monitor. Premium-only delta-neutral candidates
        and any active carry pairs (short perp + long spot hedge)."""
        from .basis import basis_skill_manifest
        from .funding import classify_funding
        book = {}
        try:
            book = dict(ctx.orchestrator.funding_provider() or {})
        except Exception:
            book = {}
        thr = ctx.scfg.funding.min_abs_funding_pct
        carry = [{"symbol": sym, **classify_funding(f, thr)} for sym, f in sorted(book.items()) if f >= thr]
        pairs = [{"symbol": pos.symbol, "tf": pos.timeframe.value, "notional_usd": round(pos.notional_usd, 2)}
                 for pos in ctx.engine.open_positions() if pos.meta.get("strategy") == "basis_carry"]
        return {"threshold_pct": thr, "carry_candidates": carry, "active_pairs": pairs,
                "skill": basis_skill_manifest(),
                "note": "Premium-only delta-neutral carry (short perp + long spot); idle in paper."}

    @app.post("/chain/register")
    def chain_register():
        """Mint the agent's ERC-8004 on-chain identity (idempotent)."""
        from .chain import register_now

        try:
            return register_now()
        except Exception as e:
            return {"ok": False, "error": str(e)[:300]}

    return app


try:  # import-time app for `uvicorn binacci.api:app`
    app = build_app()
except ImportError:  # fastapi not installed — core still usable
    app = None
