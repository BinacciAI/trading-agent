"use client";

import { useAgent, fmt } from "../useAgent";

type Status = {
  deposit_usd: number; equity_usd: number; realized_pnl_usd: number;
  unrealized_pnl_usd: number; slots_used: number; slots_max: number;
  aggregate_drawdown_usd: number; kill_switch_fired: boolean;
  venue?: string;
};

export default function Risk() {
  const [status, live] = useAgent<Status | null>("/status", null);
  const ddLimit = (status?.deposit_usd ?? 1000) * 0.30;
  const ddUsed = status?.aggregate_drawdown_usd ?? 0;
  const ddPct = ddLimit ? Math.min((ddUsed / ddLimit) * 100, 100) : 0;

  return (
    <main className="main">
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 16 }}>
        <span className={live ? "badge green" : "badge gray"}>{live ? "LIVE" : "OFFLINE"}</span>
        <span className={status?.kill_switch_fired ? "badge red" : "badge gold"}>
          🜲 {status?.kill_switch_fired ? "KILL SWITCH FIRED" : "KILL SWITCH ARMED"}</span>
      </div>

      <h2 className="section">Hard Limits — Enforced in Code, Not Prompts</h2>
      <div className="cards" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(230px, 1fr))" }}>
        <div className="card">
          <div className="lbl">Reserved Margin</div>
          <div className="val gold">Held</div>
          <p style={{ fontSize: 12, color: "var(--text-secondary)", marginTop: 6 }}>
            A fixed share of the deposit never trades, under any conditions. Untouchable by design.</p>
        </div>
        <div className="card">
          <div className="lbl">Position Slots</div>
          <div className="val">{status?.slots_used ?? 0} / {status?.slots_max ?? 5}</div>
          <p style={{ fontSize: 12, color: "var(--text-secondary)", marginTop: 6 }}>
            Hard cap on simultaneous positions. Slots return early only when a stop is locked in profit.</p>
        </div>
        <div className="card">
          <div className="lbl">Per-Position Cap</div>
          <div className="val">~3%</div>
          <p style={{ fontSize: 12, color: "var(--text-secondary)", marginTop: 6 }}>
            Even fully averaged, one position cannot exceed its deposit-share ceiling.</p>
        </div>
        <div className="card" style={{ borderColor: ddPct > 60 ? "rgba(255,77,77,0.4)" : undefined }}>
          <div className="lbl">Aggregate Drawdown</div>
          <div className={ddPct > 60 ? "val neg" : "val"}>${fmt(ddUsed)}</div>
          <div style={{ marginTop: 8, height: 6, background: "var(--bg-card)", borderRadius: 3, overflow: "hidden", border: "1px solid var(--border-soft)" }}>
            <div style={{ width: `${ddPct}%`, height: "100%", background: ddPct > 60 ? "var(--loss)" : "var(--brand-gold)" }} />
          </div>
          <p style={{ fontSize: 12, color: "var(--text-secondary)", marginTop: 6 }}>
            {fmt(ddPct)}% of the kill-switch threshold (${fmt(ddLimit)}). At 100%, everything flattens.</p>
        </div>
      </div>

      <h2 className="section">Account</h2>
      <div className="vault" style={{ maxWidth: 560 }}>
        <div className="row"><span>Deposit</span><span className="v">${fmt(status?.deposit_usd ?? 0)}</span></div>
        <div className="row"><span>Equity</span><span className="v">${fmt(status?.equity_usd ?? 0)}</span></div>
        <div className="row"><span>Realized P/L</span><span className="v">${fmt(status?.realized_pnl_usd ?? 0)}</span></div>
        <div className="row"><span>Unrealized P/L</span><span className="v">${fmt(status?.unrealized_pnl_usd ?? 0)}</span></div>
        <div className="row"><span>Venue</span><span className="v">{(status?.venue ?? "—").toUpperCase()}</span></div>
        <div className="row"><span>Kill Switch</span>
          <span className={status?.kill_switch_fired ? "v danger" : "v"}>
            {status?.kill_switch_fired ? "FIRED — manual reset required" : "Armed"}</span></div>
      </div>

      <h2 className="section">Doctrine</h2>
      <div className="vault" style={{ maxWidth: 720, borderColor: "var(--border-cyan)" }}>
        <p style={{ fontSize: 12.5, color: "var(--text-secondary)", lineHeight: 1.7 }}>
          Signal detected ≠ trade executed. Every entry passes reference → zone → filters → macro → level.
          No macro data: fail closed. No fresh reference: fail closed. Kill switch fired: nothing reopens
          without a human. Risk is enforced by the deterministic engine — the AI cannot override it.
        </p>
      </div>
    </main>
  );
}
