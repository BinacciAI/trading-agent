"""Warm-restart state persistence.

A redeploy/restart should be a non-event. Candle warmup already survives via
the BINACCI_DATA_DIR volume; this module also persists the *engine* state
(account, open + closed positions, kill switch) and recent decision traces,
so when the agent comes back it resumes with its book and history intact
instead of cold. Best-effort: any failure logs and is ignored — a corrupt
checkpoint must never crash the loop.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from .config import Timeframe
from .execution import ClosedTrade, ExecutionEngine
from .models import (
    Fill, GateResult, GateStep, Position, PositionState,
    ReferencePoint, RefKind, Side,
)

log = logging.getLogger(__name__)
STATE_VERSION = 1
MAX_POSITIONS = 600
MAX_TRACES = 300


def _iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() if dt else None


def _parse(s: Optional[str]) -> Optional[datetime]:
    return datetime.fromisoformat(s) if s else None


def _pos_to_dict(p: Position) -> dict:
    return {
        "symbol": p.symbol, "timeframe": p.timeframe.value, "side": p.side.value,
        "state": p.state.value, "averaging_done": p.averaging_done,
        "peak_gain_pct": p.peak_gain_pct, "stop_pct": p.stop_pct,
        "target_pct": p.target_pct, "opened_ts": _iso(p.opened_ts),
        "closed_ts": _iso(p.closed_ts), "close_reason": p.close_reason,
        "realized_pnl_usd": p.realized_pnl_usd, "meta": p.meta,
        "fills": [{"ts": _iso(f.ts), "price": f.price, "qty": f.qty,
                   "notional_usd": f.notional_usd, "tag": f.tag} for f in p.fills],
    }


def _pos_from_dict(d: dict) -> Position:
    p = Position(
        symbol=d["symbol"], timeframe=Timeframe(d["timeframe"]), side=Side(d["side"]),
        state=PositionState(d["state"]), averaging_done=d.get("averaging_done", 0),
        peak_gain_pct=d.get("peak_gain_pct", 0.0), stop_pct=d.get("stop_pct"),
        target_pct=d.get("target_pct", 1.0), close_reason=d.get("close_reason", ""),
        realized_pnl_usd=d.get("realized_pnl_usd", 0.0), meta=d.get("meta", {}),
    )
    p.opened_ts = _parse(d.get("opened_ts"))
    p.closed_ts = _parse(d.get("closed_ts"))
    p.fills = [Fill(ts=_parse(f["ts"]), price=f["price"], qty=f["qty"],
                    notional_usd=f["notional_usd"], tag=f["tag"]) for f in d.get("fills", [])]
    return p


def _ref_to_dict(r: ReferencePoint) -> dict:
    return {"symbol": r.symbol, "timeframe": r.timeframe.value, "kind": r.kind.value,
            "price": r.price, "ts": _iso(r.ts), "clean": r.clean, "meta": r.meta}


def _ref_from_dict(d: dict) -> ReferencePoint:
    return ReferencePoint(symbol=d["symbol"], timeframe=Timeframe(d["timeframe"]),
                          kind=RefKind(d["kind"]), price=d["price"], ts=_parse(d["ts"]),
                          clean=d.get("clean", False), meta=d.get("meta", {}))


def dump_state(engine: ExecutionEngine, orchestrator, path: Path) -> None:
    try:
        positions = engine.positions[-MAX_POSITIONS:]
        traces = []
        for tr in getattr(orchestrator, "traces", [])[-MAX_TRACES:]:
            traces.append({
                "symbol": tr.symbol, "timeframe": tr.timeframe.value,
                "ts": _iso(tr.ts), "strategy": tr.strategy, "entered": tr.entered,
                "gates": [{"step": g.step.value, "passed": g.passed, "detail": g.detail}
                          for g in tr.gates],
            })
        blob = {
            "version": STATE_VERSION,
            "account": {"deposit_usd": engine.account.deposit_usd,
                        "realized_pnl_usd": engine.account.realized_pnl_usd},
            "kill_switch_fired": engine.kill_switch_fired,
            "positions": [_pos_to_dict(p) for p in positions],
            "traces": traces,
            "references": [_ref_to_dict(r) for r in
                           getattr(getattr(orchestrator, "book", None), "refs", {}).values()],
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(blob))
        tmp.replace(path)  # atomic
    except Exception:
        log.exception("state checkpoint failed")


def load_state(engine: ExecutionEngine, orchestrator, path: Path) -> bool:
    """Restore engine + traces. Returns True if state was loaded."""
    if not path.exists():
        return False
    try:
        blob = json.loads(path.read_text())
        if blob.get("version") != STATE_VERSION:
            return False
        acct = blob.get("account", {})
        engine.account.deposit_usd = acct.get("deposit_usd", engine.account.deposit_usd)
        engine.account.realized_pnl_usd = acct.get("realized_pnl_usd", 0.0)
        engine.kill_switch_fired = bool(blob.get("kill_switch_fired", False))
        engine.positions = [_pos_from_dict(d) for d in blob.get("positions", [])]
        # rebuild closed-trade list from closed positions
        engine.closed = [
            ClosedTrade(position=p, pnl_usd=p.realized_pnl_usd, reason=p.close_reason)
            for p in engine.positions if p.state is PositionState.CLOSED
        ]
        # restore recent traces (best-effort; references rebuild from candles)
        try:
            from .orchestrator import DecisionTrace

            restored = []
            for t in blob.get("traces", []):
                dt = DecisionTrace(symbol=t["symbol"], timeframe=Timeframe(t["timeframe"]),
                                   ts=_parse(t["ts"]), strategy=t.get("strategy", "reaction"),
                                   entered=t.get("entered", False))
                dt.gates = [GateResult(step=GateStep(g["step"]), passed=g["passed"],
                                       detail=g.get("detail", "")) for g in t.get("gates", [])]
                restored.append(dt)
            orchestrator.traces = restored
        except Exception:
            log.exception("trace restore failed (non-fatal)")
        # restore market memory (reference levels) so the agent wakes warm
        try:
            book = getattr(orchestrator, "book", None)
            if book is not None:
                for d in blob.get("references", []):
                    book.update(_ref_from_dict(d))
        except Exception:
            log.exception("reference restore failed (non-fatal)")
        log.info("restored engine state: %d positions, %d closed, %d references",
                 len(engine.positions), len(engine.closed),
                 len(blob.get("references", [])))
        return True
    except Exception:
        log.exception("state restore failed")
        return False


# --------------------------------------------------------------------------
# Operator settings — persist UI/console choices across restarts so a redeploy
# never reverts the risk mode / leverage / knobs the operator selected.
# --------------------------------------------------------------------------

def _settings_path(data_dir) -> Path:
    return Path(data_dir) / "operator_settings.json"


def load_operator_settings(data_dir) -> dict:
    try:
        p = _settings_path(data_dir)
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except Exception:
        log.exception("operator settings load failed")
        return {}


def save_operator_settings(data_dir, settings: dict) -> None:
    """Merge + persist operator-chosen settings to the volume."""
    try:
        p = _settings_path(data_dir)
        p.parent.mkdir(parents=True, exist_ok=True)
        cur = load_operator_settings(data_dir)
        cur.update(settings)
        p.write_text(json.dumps(cur), encoding="utf-8")
    except Exception:
        log.exception("operator settings save failed")


def apply_operator_settings(cfg, data_dir) -> dict:
    """Re-apply the operator's saved choices over a freshly-loaded cfg so a
    UI/console change survives restarts (the saved file wins over env/defaults)."""
    s = load_operator_settings(data_dir)
    if not s:
        return {}
    try:
        if s.get("risk_mode"):
            cfg.apply_risk_mode(s["risk_mode"])
        if "perps_leverage" in s:
            cfg.perps_leverage = max(1.0, float(s["perps_leverage"]))
        if "perps_target_mult" in s:
            cfg.perps_target_mult = max(1.0, float(s["perps_target_mult"]))
        if "min_signal_strength" in s:
            cfg.min_signal_strength = max(0.0, min(1.0, float(s["min_signal_strength"])))
        if "regime_weighting" in s:
            cfg.regime_weighting = bool(s["regime_weighting"])
        tr = s.get("trailing") or {}
        if "trigger" in tr:
            cfg.trailing.trigger_pct = max(0.0, float(tr["trigger"]))
        if "initial" in tr:
            cfg.trailing.initial_sl_pct = max(0.0, float(tr["initial"]))
        if "step" in tr:
            cfg.trailing.step_pct = max(0.01, float(tr["step"]))
        cfg.export_runtime_env()
    except Exception:
        log.exception("operator settings apply failed")
    return s
