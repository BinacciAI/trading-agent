"use client";

import { useEffect, useState } from "react";
import { useAgent, fmt } from "../useAgent";

type Risk = {
  risk_mode: string; max_positions: number; reserve_pct: number;
  entry_pct_of_deposit: number; position_cap_pct_of_deposit: number;
  max_deployed_pct_of_deposit: number; aggregate_drawdown_kill_pct: number;
};
type Cfg = {
  venue: string; use_testnet: boolean; deposit_usd: number; poll_seconds: number;
  macro_refresh_seconds: number; fear_greed_refresh_seconds: number;
  poll_only_verified: boolean; warmup_backfill: boolean; quote: string;
  live_timeframes: string[]; risk: Risk; risk_modes: string[];
  credits: { per_day: number; per_month: number; breakdown: Record<string, number>; polled_symbols: number };
  cmc_key_set: boolean;
};

const MODE_BLURB: Record<string, string> = {
  conservative: "15 slots · larger entries · widest safety margin",
  balanced: "30 slots · mid-size entries · active across many markets",
  aggressive: "50 slots · smallest entries · maximum market coverage",
  custom: "manual — uses raw config values",
};

export default function Settings() {
  const [cfg, live] = useAgent<Cfg | null>("/config", null, 8000);
  const [mode, setMode] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  useEffect(() => { if (cfg?.risk?.risk_mode) setMode(cfg.risk.risk_mode); }, [cfg?.risk?.risk_mode]);

  const r = cfg?.risk;
  const modes = cfg?.risk_modes?.filter((m) => m !== "custom") ?? ["conservative", "balanced", "aggressive"];

  const switchMode = async (m: string) => {
    setBusy(true); setMsg("");
    try {
      const res = await fetch(`/agent/risk/mode?mode=${m}`, { method: "POST" });
      const j = await res.json();
      if (j.ok) { setMode(m); setMsg(`Switched to ${m} — ${j.risk.max_positions} slots`); }
      else setMsg(j.error || "switch failed");
    } catch { setMsg("agent offline — cannot switch"); }
    setBusy(false);
  };

  return (
    <main className="main">
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 16 }}>
        <span className={live ? "badge green" : "badge gray"}>{live ? "LIVE" : "OFFLINE"}</span>
        <span className="badge gold">SETTINGS</span>
      </div>

      <h2 className="section">Risk Mode</h2>
      <p style={{ fontSize: 12.5, color: "var(--text-secondary)", lineHeight: 1.7, maxWidth: 760, marginBottom: 14 }}>
        Each mode scales the number of concurrent positions and the per-entry size <i>together</i>, so a
        wider book stays just as conservative — more markets held at once, each a proportionally smaller
        slice, the same 30% kill switch and 30% reserve underneath. Switching affects new entries only.
      </p>
      <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginBottom: 8 }}>
        {modes.map((m) => (
          <button key={m} disabled={busy}
            className={m === mode ? "btn btn-primary" : "btn btn-secondary"}
            onClick={() => switchMode(m)} style={{ textTransform: "capitalize", minWidth: 130 }}>
            {m}
          </button>
        ))}
      </div>
      <p style={{ fontSize: 12, color: "var(--text-muted)", minHeight: 18 }}>
        {MODE_BLURB[mode] || ""} {msg && <span className="badge cyan" style={{ marginLeft: 8 }}>{msg}</span>}
      </p>

      <h2 className="section">Active Risk Envelope</h2>
      <div className="cards" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))" }}>
        <div className="card"><div className="lbl">Position Slots</div><div className="val">{r?.max_positions ?? "—"}</div></div>
        <div className="card"><div className="lbl">Reserve</div><div className="val gold">{fmt((r?.reserve_pct ?? 0) * 100)}%</div></div>
        <div className="card"><div className="lbl">Per-Entry</div><div className="val">{fmt((r?.entry_pct_of_deposit ?? 0) * 100)}%</div></div>
        <div className="card"><div className="lbl">Position Cap</div><div className="val">{fmt((r?.position_cap_pct_of_deposit ?? 0) * 100)}%</div></div>
        <div className="card"><div className="lbl">Max Deployed</div><div className="val cyan">{fmt((r?.max_deployed_pct_of_deposit ?? 0) * 100)}%</div></div>
        <div className="card"><div className="lbl">Kill Switch</div><div className="val neg">{fmt((r?.aggregate_drawdown_kill_pct ?? 0) * 100)}%</div></div>
      </div>

      <h2 className="section">Runtime</h2>
      <div className="vault" style={{ maxWidth: 620 }}>
        <div className="row"><span>Venue</span><span className="v">{(cfg?.venue ?? "—").toUpperCase()}{cfg?.use_testnet ? " · testnet" : ""}</span></div>
        <div className="row"><span>Deposit</span><span className="v">${fmt(cfg?.deposit_usd ?? 0)} {cfg?.quote}</span></div>
        <div className="row"><span>Markets analysed</span><span className="v">{cfg?.credits?.polled_symbols ?? "—"}</span></div>
        <div className="row"><span>Live timeframes</span><span className="v">{(cfg?.live_timeframes ?? []).join(", ") || "—"}</span></div>
        <div className="row"><span>Poll interval</span><span className="v">{cfg?.poll_seconds ?? "—"}s</span></div>
        <div className="row"><span>Macro refresh</span><span className="v">{Math.round((cfg?.macro_refresh_seconds ?? 0) / 60)}m</span></div>
        <div className="row"><span>Fear &amp; Greed refresh</span><span className="v">{cfg?.fear_greed_refresh_seconds ? Math.round(cfg.fear_greed_refresh_seconds / 60) + "m" : "off"}</span></div>
        <div className="row"><span>Warmup backfill</span><span className="v">{cfg?.warmup_backfill ? "on" : "off"}</span></div>
        <div className="row"><span>CMC key</span><span className={cfg?.cmc_key_set ? "v" : "v danger"}>{cfg?.cmc_key_set ? "set" : "missing"}</span></div>
      </div>

      <h2 className="section">CMC Credit Budget</h2>
      <div className="vault" style={{ maxWidth: 620, borderColor: "var(--border-cyan)" }}>
        <div className="row"><span>Estimated / day</span><span className="v">{fmt(cfg?.credits?.per_day ?? 0)}</span></div>
        <div className="row"><span>Estimated / month</span><span className="v">{fmt(cfg?.credits?.per_month ?? 0)}</span></div>
        <div className="row"><span>Quotes</span><span className="v">{fmt(cfg?.credits?.breakdown?.quotes ?? 0)}/day</span></div>
        <div className="row"><span>Macro</span><span className="v">{fmt(cfg?.credits?.breakdown?.macro ?? 0)}/day</span></div>
        <div className="row"><span>Fear &amp; Greed</span><span className="v">{fmt(cfg?.credits?.breakdown?.fear_greed ?? 0)}/day</span></div>
        <p style={{ fontSize: 11.5, color: "var(--text-muted)", marginTop: 8 }}>
          Lower the poll interval knob to cut quote credits (the dominant cost). Macro &amp; F&amp;G run on slower cadences by design.
        </p>
      </div>
    </main>
  );
}
