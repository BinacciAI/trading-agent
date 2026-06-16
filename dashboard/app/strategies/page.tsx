"use client";

import { useAgent, fmt } from "../useAgent";
import { AttributionBars } from "../charts";

type Cat = {
  strategy: string; skill: string; title: string; philosophy: string;
  entry_logic: string; gates: string[]; requires_macro: boolean;
};
type Strategies = {
  active: string[];
  catalog: Cat[];
  open_positions_by_strategy: Record<string, number>;
  realized_pnl_by_strategy: Record<string, number>;
};

export default function StrategiesPage() {
  const [data, live] = useAgent<Strategies | null>("/strategies", null);
  const cat = data?.catalog ?? [];
  const active = new Set(data?.active ?? []);

  return (
    <main className="main">
      <div className="toolbar">
        <span className={live ? "badge green" : "badge gray"}>{live ? "LIVE" : "OFFLINE"}</span>
        <span className="badge gold">{active.size} STRATEGIES ACTIVE</span>
      </div>

      <h2 className="section">Strategy Portfolio</h2>
      <p className="lede" style={{ marginBottom: 18 }}>
        Binacci runs a portfolio of orthogonal strategies over every market and timeframe at once.
        Each is an independent opinion that still feeds the same deterministic risk engine — more
        independent reasons to be in a market, with the slot cap and kill switch bounding total
        exposure. Positions are unique per (market, timeframe, strategy), so the strategies never collide.
      </p>

      <h2 className="section">Realized P/L by Strategy</h2>
      <div className="chartbox" style={{ marginBottom: 22 }}>
        <AttributionBars
          rows={Object.entries(data?.realized_pnl_by_strategy ?? {}).map(([label, net]) => ({ label, net }))}
          empty="no realized P/L yet — strategies are warming up" />
      </div>

      <div className="strat-grid">
        {cat.length === 0 && <div className="strat-card"><div className="sc-title">Loading…</div></div>}
        {cat.map((s) => {
          const open = data?.open_positions_by_strategy?.[s.strategy] ?? 0;
          const pnl = data?.realized_pnl_by_strategy?.[s.strategy] ?? 0;
          const on = active.has(s.strategy);
          return (
            <div key={s.strategy} className="strat-card"
                 style={{ opacity: on ? 1 : 0.55, borderColor: on ? "var(--border-gold)" : "var(--border-soft)" }}>
              <div className="sc-head">
                <div className="sc-title">{s.title}</div>
                <span className={on ? "badge green" : "badge gray"}>{on ? "ON" : "OFF"}</span>
              </div>
              <p className="sc-desc">{s.entry_logic}</p>
              <div className="sc-chips">
                {s.gates.map((g, i) => <span key={i} className="gate ok">{g.replace(/_/g, " ")}</span>)}
              </div>
              <div className="sc-tags">
                <span className={s.requires_macro ? "badge gold" : "badge cyan"}>
                  {s.requires_macro ? "macro-gated" : "counter-trend"}</span>
              </div>
              <div className="sc-foot">
                <div className="vault" style={{ padding: "10px 13px" }}>
                  <div className="row"><span>Open positions</span><span className="v">{open}</span></div>
                  <div className="row"><span>Realized P/L</span>
                    <span className={pnl >= 0 ? "v" : "v danger"}>{pnl >= 0 ? "+" : ""}{fmt(pnl)} USD</span></div>
                  <div className="row"><span>Track-2 skill</span><span className="v" style={{ fontSize: 10.5 }}>{s.skill}</span></div>
                </div>
              </div>
            </div>
          );
        })}
      </div>

      <h2 className="section">Operations Agents</h2>
      <p className="lede" style={{ marginBottom: 14 }}>
        Beyond the trading strategies, a set of operations agents supervise the book — they never place a
        trade themselves, they shape how trades are sized, routed and protected.
      </p>
      <div className="strat-grid" style={{ marginBottom: 8 }}>
        {[
          { name: "Risk Matcher", skill: "binacci-risk-matcher", desc: "Maps your deposit/margin to the fee-viable risk envelope (slots, entry size, leverage). Recommends; you apply with one tap in Controls." },
          { name: "Execution Router", skill: "binacci-execution-router", desc: "Picks the cheapest fill path (V3 0.05% vs V2 0.25%), models price impact and splits orders so slippage + gas stay below the edge." },
          { name: "Meta-Learner", skill: "binacci-meta-learner", desc: "Runs a fee-aware parameter sweep on real history and proposes leverage / trailing / target tweaks — operator approves before they go live." },
          { name: "Sentinel", skill: "binacci-sentinel", desc: "Watches for stablecoin de-pegs, flash moves and broad crashes; halts new opens the moment risk spikes." },
        ].map((a) => (
          <div key={a.name} className="strat-card">
            <div className="sc-head">
              <span className="sc-name">{a.name}</span>
              <span className="badge cyan">AGENT</span>
            </div>
            <p className="sc-desc">{a.desc}</p>
            <div className="sc-foot">
              <div className="vault" style={{ padding: "10px 13px" }}>
                <div className="row"><span>Skill</span><span className="v" style={{ fontSize: 10.5 }}>{a.skill}</span></div>
              </div>
            </div>
          </div>
        ))}
      </div>

      <h2 className="section">Shared Risk Engine</h2>
      <div className="vault" style={{ maxWidth: 760, borderColor: "var(--border-cyan)" }}>
        <p className="lede">
          Every strategy obeys the house invariant: entries are limits at a concrete level, never a
          market chase. Whatever a strategy proposes, the deterministic engine sizes it (30/70 margin,
          per-mode position cap), averages only at a level while in drawdown (per-mode multipliers), trails the
          stop into profit, caps the tail loser with a hard per-position stop, and force-flattens
          everything if aggregate floating drawdown hits the kill switch. The AI proposes; the engine disposes.
        </p>
      </div>
    </main>
  );
}
