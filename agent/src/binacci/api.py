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
                "strategy": p.meta.get("strategy", "reaction"),
                "level_kind": p.meta.get("level_kind", ""),
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
            "strategy": t.position.meta.get("strategy", "reaction"),
            "pnl_usd": round(t.pnl_usd, 2), "reason": t.reason,
            "closed": t.position.closed_ts.isoformat() if t.position.closed_ts else None,
        } for t in ctx.engine.closed]

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
        from .skill import all_skill_manifests

        return all_skill_manifests()

    @app.get("/signals")
    def signals():
        """Pending limit entries — levels parked by SimB awaiting a touch."""
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
            "log": ctx.loop.venue_log[-50:],
        }

    @app.get("/x402")
    def x402_info():
        """x402 monetization descriptor (L1 optional layer).

        Strategy specs are free during hackathon judging. Production
        monetization is dual-rail: APEX (ERC-8183) escrowed jobs at /apex
        for verifiable deliverables, and x402 pay-per-call (settled on BSC,
        EIP-3009 USDT/USDC) for low-latency spec pulls. Agents can pay this
        endpoint family via `twak x402 request`.
        """
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
            "resource": {"url": "/spec", "description": "Backtestable reaction-strategy spec",
                         "mimeType": "application/json"},
        }

    return app


try:  # import-time app for `uvicorn binacci.api:app`
    app = build_app()
except ImportError:  # fastapi not installed — core still usable
    app = None
