"""Binacci's brain — a living, persistent memory.

Nothing is ever forgotten. Three layers of durable memory, all on the
BINACCI_DATA_DIR volume:

* **Chart memory** — the accumulated 1m bars per symbol (live.py checkpoints).
* **Market memory** — the per-(symbol, timeframe) reference points / levels
  the strategies anchor on (persisted here, so the agent wakes up knowing the
  structure instead of re-deriving it).
* **Self memory** — MEMORY.md, a human-readable journal the agent writes about
  itself every checkpoint: who it is, what it's doing, what it has learned.

This module builds the MEMORY.md narrative from the live runtime.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone


def _fmt(x, p=2):
    try:
        return f"{float(x):,.{p}f}"
    except (TypeError, ValueError):
        return "—"


def per_strategy_stats(engine) -> dict:
    wins = Counter(); losses = Counter(); pnl = defaultdict(float); reasons = defaultdict(Counter)
    for t in engine.closed:
        s = t.position.meta.get("strategy", "reaction")
        pnl[s] += t.pnl_usd
        (wins if t.pnl_usd > 0 else losses)[s] += 1
        reasons[s][t.reason] += 1
    out = {}
    for s in set(list(wins) + list(losses) + list(pnl)):
        w, l = wins[s], losses[s]
        out[s] = {"wins": w, "losses": l, "trades": w + l,
                  "win_rate": round(w / (w + l) * 100, 1) if (w + l) else 0.0,
                  "pnl": round(pnl[s], 2), "reasons": dict(reasons[s])}
    return out


def lessons(engine) -> list[str]:
    """Auto-distilled lessons from the trade record."""
    out = []
    stats = per_strategy_stats(engine)
    for s, st in sorted(stats.items(), key=lambda kv: kv[1]["pnl"], reverse=True):
        if st["trades"] >= 3:
            verdict = "carrying the book" if st["pnl"] > 0 else "bleeding — review"
            out.append(f"{s}: {st['wins']}W/{st['losses']}L ({st['win_rate']}%), "
                       f"{'+' if st['pnl'] >= 0 else ''}{_fmt(st['pnl'])} USD — {verdict}.")
    # symbols that keep hitting the hard stop
    hard = Counter(t.position.symbol for t in engine.closed if t.reason == "hard_stop")
    for sym, n in hard.most_common(3):
        if n >= 2:
            out.append(f"{sym}: hard-stopped {n}x — choppy/illiquid, size down or skip.")
    return out or ["No closed trades yet — still gathering experience."]


def build_memory_md(loop) -> str:
    """Compose MEMORY.md from the live loop's runtime state."""
    scfg, rcfg, engine, orch = loop.scfg, loop.rcfg, loop.engine, loop.orch
    now = datetime.now(timezone.utc)
    snap = engine.snapshot(dict(loop.prices))
    risk = scfg.risk_summary()
    try:
        from .regime import classify_regime
        reg = classify_regime(loop.macro, loop.fear_greed_value)
    except Exception:
        reg = {"regime": "unknown", "score": 0.0, "guidance": "—"}

    stats = per_strategy_stats(engine)
    bars = {s: len(b.bars) for s, b in loop.builders.items()}
    warm = sum(1 for v in bars.values() if v >= 84)
    refs = getattr(orch, "book", None)
    ref_items = sorted(refs.refs.items())[:14] if refs else []

    L = []
    L.append("# 🧠 BINACCI — Persistent Memory")
    L.append(f"_Last updated: {now.isoformat(timespec='seconds')} · nothing is ever forgotten._\n")

    L.append("## Identity & Soul")
    L.append("I am **Binacci** — an autonomous trading agent on BNB Chain. My architecture "
             "is brains-separated-from-hands: a deterministic risk engine decides every trade, "
             "and I only execute. I read CoinMarketCap signals, sign through Trust Wallet "
             "self-custody, and trade the competition-eligible markets both ways — spot long, "
             "perps long and short — inside rules I can never override. I remember everything: "
             "every level, every trade, every lesson.\n")

    L.append("## Right Now")
    L.append(f"- **Venue:** {rcfg.venue} ({'testnet' if rcfg.use_testnet else 'mainnet'}) · "
             f"**Risk mode:** {risk['risk_mode']} ({risk['max_positions']} slots, "
             f"max {round(risk['max_deployed_pct_of_deposit']*100,1)}% deployed)")
    L.append(f"- **Regime (CMC):** {reg['regime']} (score {reg.get('score')}) — {reg.get('guidance','')}")
    L.append(f"- **Equity:** ${_fmt(snap['equity_usd'])} · realized ${_fmt(snap['realized_pnl_usd'])} · "
             f"unrealized ${_fmt(snap['unrealized_pnl_usd'])}")
    L.append(f"- **Open positions:** {snap['slots_used']}/{snap['slots_max']} · "
             f"**closed trades:** {snap['closed_trades']} · "
             f"**kill switch:** {'FIRED' if snap['kill_switch_fired'] else 'armed'}")
    L.append(f"- **Universe:** {len(scfg.symbols)} eligible markets · {warm} warm · "
             f"polls {loop.polls} · errors {loop.errors}")
    op_all = engine.open_positions()
    pp = [p for p in op_all if p.meta.get("market") == "perp"]
    sp_n = len(op_all) - len(pp)
    pl = sum(1 for p in pp if p.side.value == "long")
    L.append(f"- **Books (both live at once):** SPOT {sp_n} long · "
             f"PERPS {len(pp)} ({pl} long / {len(pp) - pl} short)\n")

    L.append("## Active Strategies")
    for s in [st.name for st in orch.strategies]:
        st = stats.get(s, {})
        L.append(f"- **{s}** — {st.get('trades',0)} trades, "
                 f"{st.get('win_rate',0)}% win, {'+' if st.get('pnl',0)>=0 else ''}{_fmt(st.get('pnl',0))} USD")
    L.append("")

    L.append("## Open Positions")
    op = engine.open_positions()
    if op:
        L.append("| Market | Side | Strategy | TF | Avg Entry | Gain% | Target |")
        L.append("|---|---|---|---|---|---|---|")
        for p in op:
            px = loop.prices.get(p.symbol, p.avg_entry)
            L.append(f"| {p.symbol} | {p.side.value} | {p.meta.get('strategy','reaction')} | "
                     f"{p.timeframe.value} | {_fmt(p.avg_entry,6)} | {round(p.gain_pct(px),3)} | {p.target_pct} |")
    else:
        L.append("_No open positions — watching, waiting for confirmation._")
    L.append("")

    L.append("## Recent Trades")
    closed = engine.closed[-12:]
    if closed:
        L.append("| Market | Side | Strategy | Exit | P/L |")
        L.append("|---|---|---|---|---|")
        for t in reversed(closed):
            L.append(f"| {t.position.symbol} | {t.position.side.value} | "
                     f"{t.position.meta.get('strategy','reaction')} | {t.reason} | "
                     f"{'+' if t.pnl_usd>=0 else ''}{_fmt(t.pnl_usd)} |")
    else:
        L.append("_None yet._")
    L.append("")

    L.append("## Lessons Learned")
    for ln in lessons(engine):
        L.append(f"- {ln}")
    L.append("")

    L.append("## Market Memory — Reference Levels")
    if ref_items:
        L.append("| Market | TF | Kind | Level | Since |")
        L.append("|---|---|---|---|---|")
        for (sym, tf), r in ref_items:
            L.append(f"| {sym} | {tf.value} | {r.kind.value} | {_fmt(r.price,6)} | "
                     f"{r.ts.isoformat(timespec='minutes')} |")
    else:
        L.append("_Building reference memory…_")
    L.append("")

    L.append("## Chart Memory")
    top = sorted(bars.values(), reverse=True)[:1]
    L.append(f"- 1m bars retained: up to {max(top) if top else 0} per symbol "
             f"(persisted to the volume; restored warm on every restart).")
    L.append(f"- Symbols with data: {sum(1 for v in bars.values() if v)} / {len(bars)}\n")

    L.append("## Risk Doctrine (never violated)")
    L.append("30% reserve · per-entry sized to the risk mode · averaging x4 then x2, only at a "
             "level and only in drawdown · stepped trailing stop into profit · 2% hard "
             "per-position stop · 30% aggregate-drawdown kill switch. The engine enforces all "
             "of it; the AI cannot override a single rule.")
    return "\n".join(L)


def write_memory(loop, path) -> None:
    """Best-effort write of MEMORY.md to the durable volume."""
    import logging
    try:
        from pathlib import Path
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(build_memory_md(loop), encoding="utf-8")
    except Exception:
        logging.getLogger(__name__).exception("MEMORY.md write failed")
