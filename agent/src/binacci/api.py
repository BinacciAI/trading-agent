"""FastAPI status server — feeds the dashboard and external monitors.

Endpoints:
* GET /status      — account snapshot + live-loop health
* GET /positions   — open positions with live gain/SL state
* GET /trades      — closed trade log
* GET /traces      — recent decision traces (the 5-gate audit trail)
* GET /spec        — generate a Track 2 strategy spec on demand
* GET /manifest    — CMC Skills Marketplace manifest
* GET /health      — liveness

On startup, if BINACCI_CMC_API_KEY is set, the live loop starts: it polls
CMC quotes, builds candles, refreshes the macro gate, runs the 5-gate
evaluations, and executes on the configured venue (paper by default).
"""

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
        self.scfg = StrategyConfig.load()
        self.rcfg = RuntimeConfig()
        self.engine = ExecutionEngine(self.scfg, deposit_usd=self.rcfg.deposit_usd)
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

    app = FastAPI(title="Binacci Agent", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware, allow_origins=["*"], allow_methods=["GET"], allow_headers=["*"],
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
        snap["prices"] = {k: round(v, 6) for k, v in ctx.prices.items()}
        return snap

    @app.get("/positions")
    def positions():
        out = []
        for p in ctx.engine.open_positions():
            px = ctx.prices.get(p.symbol, p.avg_entry)
            out.append({
                "symbol": p.symbol, "tf": p.timeframe.value, "side": p.side.value,
                "state": p.state.value, "avg_entry": p.avg_entry,
                "qty": p.qty, "notional_usd": p.notional_usd,
                "gain_pct": round(p.gain_pct(px), 3),
                "peak_gain_pct": round(p.peak_gain_pct, 3),
                "stop_pct": p.stop_pct, "target_pct": p.target_pct,
                "averaging_done": p.averaging_done,
            })
        return out

    @app.get("/trades")
    def trades():
        return [{
            "symbol": t.position.symbol, "tf": t.position.timeframe.value,
            "pnl_usd": round(t.pnl_usd, 2), "reason": t.reason,
            "closed": t.position.closed_ts.isoformat() if t.position.closed_ts else None,
        } for t in ctx.engine.closed]

    @app.get("/traces")
    def traces(limit: int = 50):
        out = []
        for tr in ctx.orchestrator.traces[-limit:]:
            out.append({
                "symbol": tr.symbol, "tf": tr.timeframe.value, "ts": tr.ts.isoformat(),
                "entered": tr.entered,
                "gates": [{"step": g.step.value, "passed": g.passed, "detail": g.detail}
                          for g in tr.gates],
            })
        return out

    @app.get("/spec")
    def spec(symbol: str = "BNB", timeframe: str = "4h"):
        from .skill import generate_strategy_spec

        return generate_strategy_spec(
            ctx.scfg, symbol=symbol.upper(), tf=Timeframe(timeframe),
            source=SyntheticSource(),
        )

    @app.get("/manifest")
    def manifest():
        from .skill import skill_manifest

        return skill_manifest()

    return app


try:  # import-time app for `uvicorn binacci.api:app`
    app = build_app()
except ImportError:  # fastapi not installed — core still usable
    app = None
