"use client";

import { useEffect, useState } from "react";
import { useAgent, fmt } from "../useAgent";

type Risk = {
  risk_mode: string; max_positions: number; reserve_pct: number;
  entry_pct_of_deposit: number; position_cap_pct_of_deposit: number;
  max_deployed_pct_of_deposit: number; aggregate_drawdown_kill_pct: number;
  perps_leverage?: number; perps_target_mult?: number;
};
type Cfg = {
  venue: string; use_testnet: boolean; deposit_usd: number; poll_seconds: number;
  macro_refresh_seconds: number; fear_greed_refresh_seconds: number;
  poll_only_verified: boolean; warmup_backfill: boolean; quote: string;
  live_timeframes: string[]; risk: Risk; risk_modes: string[];
  trade_mode?: string; allow_shorts?: boolean;
  perps_leverage?: number; perps_target_mult?: number; perp_data_source?: string;
  book_cap?: number; perp_strategies?: string[]; spot_strategies?: string[];
  credits: { per_day: number; per_month: number; breakdown: Record<string, number>; polled_symbols: number };
  cmc_key_set: boolean;
  fast_backtest?: boolean; backtest_workers?: number; cpu_count?: number;
};

const MODE_BLURB: Record<string, string> = {
  conservative: "15 slots · larger entries · 10× perps · widest safety margin",
  balanced: "30 slots · mid-size entries · 25× perps · active across many markets",
  aggressive: "50 slots · smallest entries · 50× perps · maximum market coverage",
  custom: "manual — uses raw config values",
};

export default function Settings() {
  const [cfg, live] = useAgent<Cfg | null>("/config", null, 8000);
  const [mode, setMode] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const [fastBt, setFastBt] = useState(false);
  const [workers, setWorkers] = useState(1);
  const [perfMsg, setPerfMsg] = useState("");
  useEffect(() => { if (cfg?.risk?.risk_mode) setMode(cfg.risk.risk_mode); }, [cfg?.risk?.risk_mode]);
  useEffect(() => {
    if (cfg) { setFastBt(!!cfg.fast_backtest); setWorkers(cfg.backtest_workers ?? 1); }
  }, [cfg?.fast_backtest, cfg?.backtest_workers]);

  const cpu = Math.max(1, cfg?.cpu_count ?? 1);
  const workerOpts = Array.from(new Set([1, 2, 4, 8, cpu].filter((w) => w >= 1 && w <= cpu))).sort((a, b) => a - b);

  const setPerf = async (p: { fast?: boolean; workers?: number }) => {
    setBusy(true); setPerfMsg("");
    const qs = new URLSearchParams();
    if (p.fast !== undefined) qs.set("fast_backtest", String(p.fast));
    if (p.workers !== undefined) qs.set("workers", String(p.workers));
    try {
      const res = await fetch(`/agent/backtest/perf?${qs.toString()}`, { method: "POST" });
      const j = await res.json();
      if (j.ok) {
        setFastBt(!!j.fast_backtest); setWorkers(j.backtest_workers);
        setPerfMsg(`precompute ${j.fast_backtest ? "on" : "off"} · ${j.backtest_workers} worker${j.backtest_workers > 1 ? "s" : ""}`);
      } else setPerfMsg(j.error || "update failed");
    } catch { setPerfMsg("agent offline — cannot update"); }
    setBusy(false);
  };

  const r = cfg?.risk;
  const modes = cfg?.risk_modes?.filter((m) => m !== "custom") ?? ["conservative", "balanced", "aggressive"];

  const switchMode = async (m: string) => {
    setBusy(true); setMsg("");
    try {
      const res = await fetch(`/agent/risk/mode?mode=${m}`, { method: "POST" });
      const j = await res.json();
      if (j.ok) { setMode(m); setMsg(`Switched to ${m} — ${j.risk.max_positions} slots · ${fmt(j.perps_leverage)}× perps`); }
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
        Each mode scales the number of concurrent positions and the per-entry size <i>together</i>, so spot
        book exposure stays bounded as the book widens. Modes also set the <b>perps leverage tier</b>
        (conservative 10× · balanced 25× · aggressive 50×): higher leverage controls the same notional with
        less posted margin, but scales perp P/L <i>and</i> drawdown by the same factor — so liquidation sits
        proportionally closer. The 30% reserve and 30% kill switch hold underneath every mode. Switching
        affects new entries only.
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

      <h2 className="section">Perps &amp; Leverage</h2>
      <div className="cards" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))" }}>
        <div className="card"><div className="lbl">Perps Leverage</div>
          <div className="val gold">{cfg?.perps_leverage != null ? `${fmt(cfg.perps_leverage)}×` : "—"}</div>
          <p style={{ fontSize: 11.5, color: "var(--text-muted)", marginTop: 6 }}>Set by risk mode. Spot is always 1×.</p></div>
        <div className="card"><div className="lbl">Perps TP Multiplier</div>
          <div className="val cyan">{cfg?.perps_target_mult != null ? `${fmt(cfg.perps_target_mult)}×` : "—"}</div>
          <p style={{ fontSize: 11.5, color: "var(--text-muted)", marginTop: 6 }}>Scales perp take-profit target only.</p></div>
        <div className="card"><div className="lbl">Perp Price Feed</div>
          <div className="val">{cfg?.perp_data_source === "onchain_perp_mark" ? "On-chain mark"
            : cfg?.perp_data_source === "spot_quote_fallback" ? "Spot (fallback)"
            : cfg?.perp_data_source === "spot_quote" ? "Spot quote" : "—"}</div>
          <p style={{ fontSize: 11.5, color: "var(--text-muted)", marginTop: 6 }}>Live perps manage against the venue mark.</p></div>
        <div className="card"><div className="lbl">Book Cap (per book)</div>
          <div className="val">{cfg?.book_cap ?? "—"}</div>
          <p style={{ fontSize: 11.5, color: "var(--text-muted)", marginTop: 6 }}>Max slots either book may hold.</p></div>
        <div className="card"><div className="lbl">Shorts</div>
          <div className={cfg?.allow_shorts ? "val pos" : "val"}>{cfg?.allow_shorts ? "Enabled" : "Long-only"}</div>
          <p style={{ fontSize: 11.5, color: "var(--text-muted)", marginTop: 6 }}>Perps trade both ways when enabled.</p></div>
        <div className="card"><div className="lbl">Trade Mode</div>
          <div className="val gold">{(cfg?.trade_mode ?? "spot+perps").toUpperCase()}</div>
          <p style={{ fontSize: 11.5, color: "var(--text-muted)", marginTop: 6 }}>Both books run at once.</p></div>
      </div>
      <div className="vault" style={{ maxWidth: 760, marginTop: 12 }}>
        <div className="row"><span>Perp strategies ({cfg?.perp_strategies?.length ?? 0})</span>
          <span className="v">{(cfg?.perp_strategies ?? []).map((s) => s.replace(/_/g, " ")).join(", ") || "—"}</span></div>
        <div className="row"><span>Spot strategies ({cfg?.spot_strategies?.length ?? 0})</span>
          <span className="v">{(cfg?.spot_strategies ?? []).map((s) => s.replace(/_/g, " ")).join(", ") || "—"}</span></div>
      </div>

      <h2 className="section">Backtest Performance</h2>
      <p className="lede" style={{ marginBottom: 14 }}>
        Speed-only controls — neither changes trading behaviour or backtest results (both are
        gated by an equivalence harness that proves identical trades). <b style={{ color: "var(--text-primary)" }}>Precompute</b> computes
        each causal indicator once per run instead of every bar; <b style={{ color: "var(--text-primary)" }}>sweep workers</b> fans
        the 146-market universe sweep across processes (byte-identical to serial).
      </p>
      <div className="cards" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))" }}>
        <div className="card">
          <div className="lbl">Precompute (Fast Backtest)</div>
          <div style={{ display: "flex", gap: 8, margin: "8px 0 2px" }}>
            <button disabled={busy} className={fastBt ? "btn btn-primary" : "btn btn-secondary"}
              onClick={() => setPerf({ fast: true })} style={{ minWidth: 64 }}>On</button>
            <button disabled={busy} className={!fastBt ? "btn btn-primary" : "btn btn-secondary"}
              onClick={() => setPerf({ fast: false })} style={{ minWidth: 64 }}>Off</button>
          </div>
          <p style={{ fontSize: 11.5, color: "var(--text-muted)", marginTop: 6 }}>
            Causal-indicator precompute. Trade-identical; extra speed on every run.
          </p>
        </div>
        <div className="card">
          <div className="lbl">Sweep Workers</div>
          <div style={{ display: "flex", gap: 6, margin: "8px 0 2px", flexWrap: "wrap" }}>
            {workerOpts.map((w) => (
              <button key={w} disabled={busy} className={workers === w ? "btn btn-primary" : "btn btn-secondary"}
                onClick={() => setPerf({ workers: w })} style={{ minWidth: 46, padding: "9px 12px" }}>{w}</button>
            ))}
          </div>
          <p style={{ fontSize: 11.5, color: "var(--text-muted)", marginTop: 6 }}>
            Parallel processes for the universe sweep. This host has <b style={{ color: "var(--text-primary)" }}>{cpu}</b> core{cpu > 1 ? "s" : ""}; 1 = serial.
          </p>
        </div>
      </div>
      <p style={{ fontSize: 12, color: "var(--text-muted)", minHeight: 18, marginTop: 8 }}>
        {perfMsg && <span className="badge cyan">{perfMsg}</span>}
        {cpu <= 1 && <span style={{ marginLeft: perfMsg ? 8 : 0 }}>Single-core host — workers caps at 1; parallelism scales on a multi-core deploy.</span>}
      </p>

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
