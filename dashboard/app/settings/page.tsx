"use client";

import { useEffect, useState } from "react";
import { useAgent, fmt } from "../useAgent";
import { AttributionBars } from "../charts";

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
  min_signal_strength?: number; regime_weighting?: boolean; min_edge_gate?: boolean;
  trailing?: { trigger: number; initial: number; step: number }; trading_halted?: boolean;
};
type Status = { regime?: string };
type AttrRow = { trades: number; win_rate: number; net: number };
type Attr = { by_strategy: Record<string, AttrRow> };
type Fees = { min_edge_gate?: boolean;
  realized?: { gross_usd: number; fees_usd: number; net_usd: number; fee_drag_pct_of_gross: number | null };
  breakeven_move_pct_incl_gas?: { spot: number; perp: number };
  model?: { swap_fee_pct_per_swap?: number; perp_fee_pct_per_side?: number; gas_usd_per_action?: number } };

const MODE_BLURB: Record<string, string> = {
  conservative: "6 slots · largest entries · 10× perps · widest safety margin",
  balanced: "10 slots · mid-size entries · 25× perps · balanced exposure",
  aggressive: "14 slots · more, smaller entries · 50× perps · maximum aggression",
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
  const [status] = useAgent<Status>("/status", {}, 5000);
  const [attr] = useAgent<Attr>("/attribution", { by_strategy: {} }, 6000);
  const [fees] = useAgent<Fees>("/fees", {}, 10000);
  const [lev, setLev] = useState(""); const [str, setStr] = useState("");
  const [tgt, setTgt] = useState(""); const [trg, setTrg] = useState("");
  const [ini, setIni] = useState(""); const [stp, setStp] = useState("");
  const [rw, setRw] = useState<boolean | null>(null);
  const [synced, setSynced] = useState(false); const [ctlMsg, setCtlMsg] = useState("");
  useEffect(() => { if (cfg?.risk?.risk_mode) setMode(cfg.risk.risk_mode); }, [cfg?.risk?.risk_mode]);
  useEffect(() => {
    if (cfg) { setFastBt(!!cfg.fast_backtest); setWorkers(cfg.backtest_workers ?? 1); }
  }, [cfg?.fast_backtest, cfg?.backtest_workers]);

  useEffect(() => {
    if (synced || cfg?.perps_leverage == null) return;
    setLev(String(cfg.perps_leverage)); setStr(String(cfg.min_signal_strength ?? 0));
    setTgt(String(cfg.perps_target_mult ?? 2)); setTrg(String(cfg.trailing?.trigger ?? 0.4));
    setIni(String(cfg.trailing?.initial ?? 0.2)); setStp(String(cfg.trailing?.step ?? 0.1));
    setRw(cfg.regime_weighting ?? true); setSynced(true);
  }, [cfg, synced]);
  const applyCtl = async () => {
    const q = new URLSearchParams();
    if (lev) q.set("perps_leverage", lev); if (str !== "") q.set("min_strength", str);
    if (tgt) q.set("perps_target_mult", tgt); if (trg) q.set("trail_trigger", trg);
    if (ini) q.set("trail_initial", ini); if (stp) q.set("trail_step", stp);
    if (rw != null) q.set("regime_weighting", String(rw));
    try { const j = await (await fetch(`/agent/control?${q.toString()}`, { method: "POST" })).json();
      setCtlMsg(j?.ok ? `Applied ${Object.keys(j.applied || {}).length} change(s) to the live engine.` : "failed"); }
    catch { setCtlMsg("agent offline"); }
    setTimeout(() => setCtlMsg(""), 4000);
  };
  const halted = cfg?.trading_halted;
  const doHalt = async () => { try { await fetch("/agent/halt?reason=operator", { method: "POST" }); } catch {} setCtlMsg("Trading halted — new opens blocked."); setTimeout(() => setCtlMsg(""), 4000); };
  const doResume = async () => { try { await fetch("/agent/venue/resume", { method: "POST" }); } catch {} setCtlMsg("Trading resumed."); setTimeout(() => setCtlMsg(""), 4000); };
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
        {status.regime && status.regime !== "unknown" && <span className="badge gray">{status.regime.replace("_", "-")}</span>}
        {halted && <span className="badge red">HALTED</span>}
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

      <h2 className="section">Live Tuning</h2>
      <div className="vault" style={{ marginBottom: 20, maxWidth: 820 }}>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(150px,1fr))", gap: 12 }}>
          <Ctl label="Perps leverage" v={lev} set={setLev} step="1" />
          <Ctl label="Strength gate (0–1)" v={str} set={setStr} step="0.05" />
          <Ctl label="Perp TP mult" v={tgt} set={setTgt} step="0.25" />
          <Ctl label="Trail trigger %" v={trg} set={setTrg} step="0.05" />
          <Ctl label="Trail lock %" v={ini} set={setIni} step="0.02" />
          <Ctl label="Trail step %" v={stp} set={setStp} step="0.01" />
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 14, marginTop: 14, flexWrap: "wrap" }}>
          <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13, color: "var(--text-secondary)", cursor: "pointer" }}>
            <input type="checkbox" checked={!!rw} onChange={(e) => setRw(e.target.checked)} /> Regime-weighted allocation
          </label>
          {halted
            ? <button className="btn btn-secondary" onClick={doResume}>Resume</button>
            : <button className="btn btn-danger" onClick={doHalt}>◼ Halt new opens</button>}
          <span style={{ flex: 1 }} />
          <button className="btn btn-primary" onClick={applyCtl}>Apply to engine</button>
        </div>
        {ctlMsg && <p style={{ fontSize: 12, marginTop: 8 }}><span className="badge cyan">{ctlMsg}</span></p>}
      </div>

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

      <h2 className="section">On-Chain Fees</h2>
      <div className="vault" style={{ marginBottom: 20, maxWidth: 820 }}>
        <div className="statline" style={{ border: "none", background: "transparent", padding: 0, marginBottom: 4 }}>
          <span>Gross <b className={(fees.realized?.gross_usd ?? 0) >= 0 ? "pos" : "neg"}>{fmt(fees.realized?.gross_usd ?? 0)}</b></span>
          <span>Fees paid <b className="neg">−{fmt(fees.realized?.fees_usd ?? 0)}</b></span>
          <span>Net <b className={(fees.realized?.net_usd ?? 0) >= 0 ? "pos" : "neg"}>{fmt(fees.realized?.net_usd ?? 0)}</b></span>
          <span>Fee drag <b>{fees.realized?.fee_drag_pct_of_gross != null ? fmt(fees.realized.fee_drag_pct_of_gross) + "%" : "—"}</b></span>
        </div>
        <div className="row"><span>Breakeven move · spot</span><span className="v">{fmt(fees.breakeven_move_pct_incl_gas?.spot ?? 0)}%</span></div>
        <div className="row"><span>Breakeven move · perps</span><span className="v">{fmt(fees.breakeven_move_pct_incl_gas?.perp ?? 0)}%</span></div>
        <div className="row"><span>Fee-aware entry gate</span><span className="v">{fees.min_edge_gate ? "ON" : "off (paper)"}</span></div>
        <p style={{ fontSize: 11.5, color: "var(--text-muted)", marginTop: 8 }}>
          Swap {fees.model?.swap_fee_pct_per_swap ?? "—"}%/swap · perp {fees.model?.perp_fee_pct_per_side ?? "—"}%/side · gas ${fees.model?.gas_usd_per_action ?? "—"}/action. Gas is fixed per action, so breakeven falls as position size rises.
        </p>
      </div>

      <h2 className="section">Net P/L by Strategy</h2>
      <div className="chartbox" style={{ marginBottom: 22 }}>
        <AttributionBars rows={Object.entries(attr.by_strategy).map(([label, a]) => ({ label, net: a.net }))} empty="no realized/open P/L yet" />
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

function Ctl({ label, v, set, step }: { label: string; v: string; set: (s: string) => void; step: string }) {
  return (
    <div className="sel-wrap">
      <span className="sel-lbl">{label}</span>
      <input type="number" step={step} value={v} onChange={(e) => set(e.target.value)}
        style={{ background: "var(--bg-card)", border: "1px solid var(--border-soft)", borderRadius: "var(--radius-md)",
          color: "var(--text-primary)", padding: "8px 12px", fontFamily: "var(--font-mono)", fontSize: 13, outline: "none" }} />
    </div>
  );
}
