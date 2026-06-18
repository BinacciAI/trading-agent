"""Meta-learner agent — self-optimizes the risk/edge knobs.

Runs a focused, fee-aware parameter sweep on the agent's own accumulated data
(the checkpoint source; synthetic fallback) and proposes the config that
maximizes net-of-fee risk-adjusted return (net Calmar = net% / drawdown%). It
closes the loop: the same fast-backtest engine the agent trades on, scored on
real data, recommending param updates. Propose-only by default; opt-in guarded
auto-apply via BINACCI_AUTO_OPTIMIZE.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

from .config import StrategyConfig, Timeframe, TrailingModel
from .data import make_source
from .backtest import run_universe_backtest

_JOB: dict = {"status": "idle", "proposal": None, "started": None, "error": None}
_LOCK = threading.Lock()

TIGHT = (0.30, 0.22, 0.07)
WIDE = (0.60, 0.35, 0.15)


def _candidates() -> list[dict]:
    out = []
    for lev in (10, 25):
        for trail, tn in ((TIGHT, "tight"), (WIDE, "wide")):
            for tm in (2, 3):
                out.append({"label": f"L{lev}/{tn}/x{tm}", "perps_leverage": float(lev),
                            "trailing": trail, "perps_target_mult": float(tm)})
    return out


def _cfg_for(base: StrategyConfig, c: dict) -> StrategyConfig:
    cfg = StrategyConfig()
    cfg.allow_shorts = True
    # preserve the operator's structural sizing; vary only the edge knobs
    cfg.margin.entry_pct_of_working = base.margin.entry_pct_of_working
    cfg.margin.averaging_multipliers = base.margin.averaging_multipliers
    cfg.risk.max_positions = base.risk.max_positions
    cfg.perps_leverage = c["perps_leverage"]
    cfg.perps_target_mult = c["perps_target_mult"]
    cfg.trailing = TrailingModel(trigger_pct=c["trailing"][0], initial_sl_pct=c["trailing"][1], step_pct=c["trailing"][2])
    return cfg


def _score(net_pct: float, dd_pct: float) -> float:
    return round(net_pct / max(dd_pct, 0.5), 3)


def run_optimization(base: StrategyConfig, rcfg, symbols: list[str], source: str = "checkpoint",
                     bars: int = 500, deposit: float = 1000.0) -> dict:
    os.environ.setdefault("BINACCI_FAST_BACKTEST", "1")
    src = make_source(source, rcfg)
    rows = []
    for c in _candidates():
        try:
            r = run_universe_backtest(_cfg_for(base, c), src, symbols, Timeframe.M15,
                                      bars=bars, deposit_usd=deposit, eval_every=2)
        except Exception:
            continue
        net = r["total_pnl_usd"] / (len(symbols) * deposit) * 100 if symbols else 0.0
        dd = max((s["max_drawdown_pct"] for s in r["per_symbol"]), default=0.0)
        rows.append({"label": c["label"], "perps_leverage": c["perps_leverage"],
                     "perps_target_mult": c["perps_target_mult"],
                     "trailing": {"trigger": c["trailing"][0], "initial": c["trailing"][1], "step": c["trailing"][2]},
                     "net_pct": round(net, 3), "drawdown_pct": round(dd, 2), "score": _score(net, dd)})
    rows.sort(key=lambda x: (x["net_pct"] > 0, x["score"]), reverse=True)
    best = rows[0] if rows else None
    cur_lev, cur_tm = base.perps_leverage, base.perps_target_mult
    return {"source": source, "symbols": len(symbols), "candidates": rows, "best": best,
            "current": {"perps_leverage": cur_lev, "perps_target_mult": cur_tm,
                        "trailing": {"trigger": base.trailing.trigger_pct,
                                     "initial": base.trailing.initial_sl_pct, "step": base.trailing.step_pct}},
            "ts": time.time()}


def start_job(base: StrategyConfig, rcfg, symbols: list[str], data_dir: str) -> dict:
    with _LOCK:
        if _JOB["status"] == "running":
            return dict(_JOB)
        _JOB.update(status="running", proposal=None, started=time.time(), error=None)

    def _work():
        try:
            prop = run_optimization(base, rcfg, symbols)
            try:
                Path(data_dir).mkdir(parents=True, exist_ok=True)
                (Path(data_dir) / "optimizer_proposal.json").write_text(json.dumps(prop))
            except Exception:
                pass
            with _LOCK:
                _JOB.update(status="done", proposal=prop)
        except Exception as e:  # noqa: BLE001
            with _LOCK:
                _JOB.update(status="error", error=str(e))

    threading.Thread(target=_work, daemon=True).start()
    return dict(_JOB)


def last_proposal(data_dir: str) -> dict:
    with _LOCK:
        if _JOB["proposal"]:
            return dict(_JOB)
    try:
        p = Path(data_dir) / "optimizer_proposal.json"
        if p.exists():
            return {"status": "done", "proposal": json.loads(p.read_text()), "started": None, "error": None}
    except Exception:
        pass
    return dict(_JOB)
