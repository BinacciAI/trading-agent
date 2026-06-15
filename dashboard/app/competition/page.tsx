"use client";

import { useState } from "react";
import { useAgent, fmt } from "../useAgent";

type Comp = {
  track: number; contract: string; explorer: string; wallet: string | null;
  registered: boolean; twak_installed: boolean; eligible_tokens: number;
  markets_active: number; min_trades_per_day: number; trades_today: number;
  opens_today: number; activity_today: number; min_trade_met: boolean;
  total_trades: number; symbols_traded: string[]; venue: string;
  testnet: boolean; live_trading: boolean;
};

function Check({ ok, pending }: { ok: boolean; pending?: boolean }) {
  return <span className={ok ? "chk done" : pending ? "chk pend" : "chk todo"}>{ok ? "✓" : pending ? "…" : "○"}</span>;
}

export default function Competition() {
  const [c, live] = useAgent<Comp | null>("/competition", null, 8000);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");

  const register = async () => {
    setBusy(true); setMsg("");
    try {
      const r = await fetch("/agent/compete/register", { method: "POST" });
      const j = await r.json();
      setMsg(j.ok ? "Registration submitted on-chain ✓" : (j.error || "registration failed"));
    } catch { setMsg("agent offline"); }
    setBusy(false);
  };

  const venueLabel = c?.live_trading ? "LIVE · PANCAKESWAP" : c?.venue === "paper" ? "PAPER" : `${(c?.venue ?? "").toUpperCase()} · TESTNET`;

  return (
    <main className="main">
      <div className="toolbar">
        <span className={live ? "badge green" : "badge gray"}>{live ? "LIVE" : "OFFLINE"}</span>
        <span className="badge gold">TRACK 1 · LIVE TRADING</span>
        <span className={c?.live_trading ? "badge green" : "badge cyan"}>{venueLabel}</span>
      </div>

      <h2 className="section">Competition Readiness</h2>
      <div className="comp-grid">
        <div className="comp-check">
          <div className="cc-row"><Check ok={!!c?.registered} pending={c?.twak_installed && !c?.registered} />
            <div><div className="cc-title">On-chain registration</div>
              <div className="cc-sub">Agent wallet recorded on the competition contract.</div></div>
          </div>
          <div className="cc-row"><Check ok={!!c?.live_trading} pending={c?.venue !== "paper"} />
            <div><div className="cc-title">Live execution venue</div>
              <div className="cc-sub">PancakeSwap mainnet via Trust Wallet Agent Kit (self-custody).</div></div>
          </div>
          <div className="cc-row"><Check ok={!!c?.min_trade_met} />
            <div><div className="cc-title">Minimum 1 trade / day</div>
              <div className="cc-sub">{c?.activity_today ?? 0} trade(s) today · 7 required over the week.</div></div>
          </div>
          <div className="cc-row"><Check ok={(c?.eligible_tokens ?? 0) >= 100} />
            <div><div className="cc-title">Eligible-token universe</div>
              <div className="cc-sub">{c?.eligible_tokens ?? 0} CMC-listed BEP-20 tokens loaded — only these count.</div></div>
          </div>
          <button className="btn btn-primary" style={{ marginTop: 14, width: "100%" }}
                  onClick={register} disabled={busy || !!c?.registered}>
            {c?.registered ? "✓ Registered on-chain" : busy ? "Submitting…" : "▶ Register agent on-chain"}
          </button>
          {msg && <p className="cc-msg">{msg}</p>}
        </div>

        <div className="comp-side">
          <div className="cards" style={{ gridTemplateColumns: "1fr 1fr" }}>
            <div className="card"><div className="lbl">Trades Today</div>
              <div className={c?.min_trade_met ? "val pos" : "val"}>{c?.activity_today ?? 0}<span className="val-sub"> / 1</span></div></div>
            <div className="card"><div className="lbl">Total Trades</div><div className="val">{c?.total_trades ?? 0}</div></div>
            <div className="card"><div className="lbl">Eligible Tokens</div><div className="val cyan">{c?.eligible_tokens ?? 0}</div></div>
            <div className="card"><div className="lbl">Markets Active</div><div className="val">{c?.markets_active ?? 0}</div></div>
          </div>
          <div className="vault" style={{ marginTop: 12 }}>
            <div className="title">🏁 On-Chain Entry</div>
            <div className="row"><span>Contract</span>
              <a className="v" href={c?.explorer} target="_blank" rel="noreferrer"
                 style={{ color: "var(--brand-cyan)" }}>{c ? `${c.contract.slice(0, 10)}…${c.contract.slice(-6)}` : "—"}</a></div>
            <div className="row"><span>Agent Wallet</span><span className="v">{c?.wallet ? `${c.wallet.slice(0, 8)}…${c.wallet.slice(-6)}` : "self-custody"}</span></div>
            <div className="row"><span>TWAK CLI</span><span className={c?.twak_installed ? "v" : "v danger"}>{c?.twak_installed ? "ready" : "not installed"}</span></div>
            <div className="row"><span>Registered</span><span className={c?.registered ? "v" : "v danger"}>{c?.registered ? "yes" : "pending"}</span></div>
          </div>
        </div>
      </div>

      <h2 className="section">Eligible Tokens Traded</h2>
      <div className="chip-wrap">
        {(c?.symbols_traded ?? []).length === 0 && <span className="muted" style={{ fontSize: 12.5 }}>No eligible-token trades yet — the agent trades only the competition list.</span>}
        {(c?.symbols_traded ?? []).map((s) => <span key={s} className="tok-chip">{s}</span>)}
      </div>

      <h2 className="section">Rules</h2>
      <div className="vault" style={{ maxWidth: 760, borderColor: "var(--border-cyan)" }}>
        <p className="lede">
          Track 1 is a live, on-chain trading competition (Jun 22–28). Register the agent wallet before the
          window opens. Only trades in the fixed CMC eligible-token list count. At least one trade per day
          (seven over the week). Hold a non-zero balance of in-scope assets at the start — any hour that
          begins with the portfolio worth $1 or less scores 0% for that hour, so capital stays deployed.
          Execution is self-custodial through the Trust Wallet Agent Kit; keys never leave the wallet.
        </p>
      </div>
    </main>
  );
}
