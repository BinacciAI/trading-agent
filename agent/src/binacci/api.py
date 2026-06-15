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


#: cache for the heavy universe backtest: key -> (ts, result)
_UNIVERSE_CACHE: dict = {}


def _default_source() -> str:
    """Default backtest data source (BINACCI_BACKTEST_SOURCE), e.g. set
    'cmc' on Railway where the CMC key + OHLCV plan exist."""
    import os
    return os.environ.get("BINACCI_BACKTEST_SOURCE", "synthetic")


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
            "risk": ctx.scfg.risk_summary(),
            "risk_modes": [m.value for m in RiskMode],
            "credits": ctx.loop.credit_estimate(),
            "cmc_key_set": bool(ctx.rcfg.cmc_api_key),
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
        return {"ok": True, "risk": ctx.scfg.risk_summary()}

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
            "log": ctx.loop.venue_log[-50:],
        }

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

    @app.get("/regime")
    def regime():
        """Macro Regime Classifier (CMC-data skill) — live classification."""
        from .regime import classify_regime, regime_skill_manifest

        macro = ctx.loop.macro
        fg = ctx.loop.fear_greed_value
        out = classify_regime(macro, fg)
        out["skill"] = regime_skill_manifest()["name"]
        return out

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
