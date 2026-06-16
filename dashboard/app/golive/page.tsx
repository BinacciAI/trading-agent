"use client";

import { useState } from "react";
import { useAgent } from "../useAgent";

type Check = { name: string; ok: boolean; detail: string };
type GoLive = { mode?: string; venue?: string; testnet?: boolean; ready_to_flip?: boolean;
  checks?: Check[]; next_steps?: string[]; warnings?: string[] };

export default function GoLive() {
  const [g, live] = useAgent<GoLive>("/golive", {}, 6000);
  const [pf, setPf] = useState("");
  const runPreflight = async () => {
    setPf("running…");
    try { const j = await (await fetch("/agent/venue/preflight", { method: "POST" })).json();
      setPf(j.preflight_ok ? "preflight OK" : `preflight FAILED — ${j.detail || ""}`); }
    catch { setPf("agent offline"); }
  };
  const isLive = g.mode === "LIVE";

  return (
    <main className="main">
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 16, flexWrap: "wrap" }}>
        <span className={live ? "badge green" : "badge gray"}>{live ? "LIVE" : "OFFLINE"}</span>
        <span className={isLive ? "badge red" : "badge gold"}>{isLive ? "REAL FUNDS" : "PAPER"}</span>
        <span className="badge gray">venue: {g.venue ?? "—"}{g.testnet ? " · testnet" : ""}</span>
        <span className={g.ready_to_flip ? "badge green" : "badge gold"}>{g.ready_to_flip ? "READY TO FLIP" : "NOT READY"}</span>
      </div>

      <h2 className="section">Go-Live Readiness</h2>
      <p style={{ fontSize: 12.5, color: "var(--text-secondary)", lineHeight: 1.7, maxWidth: 760, marginBottom: 14 }}>
        Real-money trading runs on the hardened venue path — preflight, fill reconciliation, rollback on
        failure, and auto-halt on desync. The first orders are dust-sized by the ramp cap. Flipping to live
        is a deliberate operator action (env change); this page checks you're ready.
      </p>

      <div className="comp-check" style={{ marginBottom: 18 }}>
        {(g.checks ?? []).map((c, i) => (
          <div className="cc-row" key={i}>
            <div className={c.ok ? "chk done" : "chk pend"}>{c.ok ? "✓" : "!"}</div>
            <div>
              <div className="cc-title">{c.name}</div>
              <div className="cc-sub">{c.detail}</div>
            </div>
          </div>
        ))}
        {(g.checks ?? []).length === 0 && <div className="cc-sub">loading readiness…</div>}
      </div>

      <h2 className="section">Steps to Flip</h2>
      <div className="vault" style={{ maxWidth: 820, marginBottom: 18 }}>
        <ol style={{ margin: 0, paddingLeft: 20, color: "var(--text-secondary)", fontSize: 13, lineHeight: 1.9 }}>
          {(g.next_steps ?? []).map((s, i) => <li key={i}>{s}</li>)}
        </ol>
      </div>

      <h2 className="section">Env to Flip Live</h2>
      <pre style={{ background: "var(--bg-elev)", border: "1px solid var(--border-soft)", borderRadius: 10,
        padding: "14px 16px", fontFamily: "var(--font-mono)", fontSize: 12, color: "var(--text-secondary)",
        overflow: "auto", maxWidth: 820 }}>{`BINACCI_VENUE=perps           # or pancake (perps are fee-advantaged)
BINACCI_USE_TESTNET=false
BINACCI_WALLET_ADDRESS=0x…     # your funded BSC wallet
BINACCI_GOLIVE_MAX_USD=25      # dust-cap per order until verified
# wallet auth (Trust Wallet Agent Kit):
TWAK_ACCESS_ID / TWAK_HMAC_SECRET / TWAK_WALLET_PASSWORD
# fund the wallet: USDT (capital) + ~$10–20 BNB for gas`}</pre>

      <h2 className="section">Preflight</h2>
      <div style={{ display: "flex", alignItems: "center", gap: 14, marginBottom: 18 }}>
        <button className="btn btn-secondary" onClick={runPreflight}>Run venue preflight</button>
        {pf && <span className={pf.includes("OK") ? "badge green" : pf === "running…" ? "badge gold" : "badge red"}>{pf}</span>}
      </div>

      {(g.warnings ?? []).map((w, i) => (
        <div key={i} className="demo-note" style={{ borderColor: "rgba(255,77,77,0.4)", background: "rgba(255,77,77,0.06)", color: "var(--loss)" }}>⚠ {w}</div>
      ))}
    </main>
  );
}
